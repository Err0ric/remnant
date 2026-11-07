"""Import the SigmaHQ core rule package (D211): the pinned release fetched on an admin's
click with its SHA-256 checked first, or the zip uploaded. No network: the HTTP client is
a fake transport serving a small synthetic package."""

import hashlib
import io
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.core.errors import RuleRejectedError
from app.detect import sigmahq
from app.main import create_app

FIX = Path(__file__).parent.parent / "fixtures" / "logs"
ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"

GOOD_ID = "55555555-5555-4555-8555-555555555555"
BROKEN_ID = "66666666-6666-4666-8666-666666666666"
GOOD = f"""title: SSH failed password
id: {GOOD_ID}
author: alice
level: medium
tags: [attack.credential-access, attack.t1110]
logsource: {{product: linux}}
detection:
  k: ['Failed password']
  condition: k
"""
# Does not compile: a Windows category with no channel mapping.
BROKEN = f"""title: Unknown Windows category
id: {BROKEN_ID}
logsource: {{product: windows, category: file_rename}}
detection:
  s: {{TargetFilename|endswith: '.x'}}
  condition: s
"""
# pySigma raises AttributeError on a number as the id; the import must skip it.
NUMBER_ID = """title: Number id
id: 12345
logsource: {product: linux}
detection:
  k: ['x']
  condition: k
"""


def make_zip(members: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


PACKAGE = make_zip(
    {
        "rules/linux/ssh_failed.yml": GOOD,
        "rules/windows/unknown_category.yml": BROKEN,
        "rules/linux/number_id.yml": NUMBER_ID,
        "LICENSE.Detection.Rules.md": "Detection Rule License text",
    }
)


class FakeGitHub:
    """github.com redirects to the asset store, which serves `body`."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.host == "github.com":
            return httpx.Response(
                302, headers={"location": "https://release-assets.githubusercontent.com/a/1"}
            )
        return httpx.Response(200, content=self.body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fake = FakeGitHub(PACKAGE)
    monkeypatch.setattr(sigmahq, "default_client", fake.client)
    monkeypatch.setattr(sigmahq, "ASSET_SHA256", hashlib.sha256(PACKAGE).hexdigest())
    logs = tmp_path / "logs"
    (logs / "lin").mkdir(parents=True)
    shutil.copy(FIX / "linux_sshd" / "sample.log", logs / "lin" / "auth.log")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    res = admin.post(
        "/api/sources",
        json={
            "source_id": "lin_auth",
            "format": "syslog",
            "path": str(logs / "lin"),
            "template_id": "linux_sshd",
        },
        headers=h,
    )
    assert res.status_code == 201, res.text
    res = admin.post("/api/users", json={"username": "ana", "role": "analyst"}, headers=h)
    admin.post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    login = TestClient(app, base_url=BASE).post(
        "/api/auth/login", json={"username": "ana", "password": USER_PW, "client": "cli"}
    )
    ana = TestClient(
        app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    return {
        "admin": admin,
        "ana": ana,
        "h": h,
        "fake": fake,
        "db": tmp_path / "data" / "meta.sqlite",
    }


def audit_rows(db: Path) -> list[tuple[str, str, str | None, str]]:
    with sqlite3.connect(db) as con:
        return [
            (str(a), str(o), u, str(d))
            for a, o, u, d in con.execute(
                "SELECT action, outcome, user_id, detail FROM audit_log"
                " WHERE action = 'rule.import' ORDER BY audit_id"
            )
        ]


def admin_id(db: Path) -> str:
    with sqlite3.connect(db) as con:
        (uid,) = con.execute("SELECT user_id FROM users WHERE username = 'admin'").fetchone()
    return str(uid)


def test_nothing_is_fetched_until_the_admin_asks(lab: dict[str, Any]) -> None:
    assert lab["fake"].requests == []
    assert lab["admin"].get("/api/rules").json() == []
    assert lab["admin"].get("/api/rules/sigmahq").json()["release"] == sigmahq.RELEASE_TAG
    assert lab["fake"].requests == []


def test_pinned_release_imports_disabled_rules_that_are_recommended(lab: dict[str, Any]) -> None:
    res = lab["admin"].post("/api/rules/import/sigmahq", headers=lab["h"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert lab["fake"].requests == [
        sigmahq.ASSET_URL,
        "https://release-assets.githubusercontent.com/a/1",
    ]
    assert (body["files"], body["accepted"], body["skipped"], body["not_compiling"]) == (3, 1, 1, 1)
    reasons = {r["path"]: r["reason"] for r in body["refusals"]}
    assert reasons["rules/linux/number_id.yml"] == "Rule id must be text"
    assert "file_rename" in reasons["rules/windows/unknown_category.yml"]
    rules = lab["admin"].get("/api/rules").json()
    assert [(r["rule_id"], r["enabled"]) for r in rules] == [(GOOD_ID, False)]
    rec = lab["admin"].get("/api/rules/recommended").json()
    assert [(r["rule_id"], r["source_ids"]) for r in rec] == [(GOOD_ID, ["lin_auth"])]
    [(_, outcome, uid, details)] = audit_rows(lab["db"])
    assert (outcome, uid) == ("success", admin_id(lab["db"]))
    detail = json.loads(details)
    assert (detail["origin"], detail["release"], detail["sha256"]) == (
        "sigmahq",
        sigmahq.RELEASE_TAG,
        sigmahq.ASSET_SHA256,
    )
    assert (detail["accepted"], detail["skipped"], detail["not_compiling"]) == (1, 1, 1)


def test_hash_mismatch_imports_nothing(lab: dict[str, Any]) -> None:
    lab["fake"].body = PACKAGE + b"tampered"
    res = lab["admin"].post("/api/rules/import/sigmahq", headers=lab["h"])
    assert res.status_code == 400
    assert "does not match the pinned SHA-256" in res.json()["detail"]
    assert lab["admin"].get("/api/rules").json() == []
    assert lab["admin"].get("/api/rules/imports").json() == []
    [(_, outcome, uid, details)] = audit_rows(lab["db"])
    assert (outcome, uid) == ("failure", admin_id(lab["db"]))
    assert sigmahq.RELEASE_TAG in details


def test_reimport_is_idempotent_and_keeps_enabled_state(lab: dict[str, Any]) -> None:
    admin, h = lab["admin"], lab["h"]
    assert admin.post("/api/rules/import/sigmahq", headers=h).status_code == 200
    admin.post("/api/rules/enabled", json={"rule_ids": [GOOD_ID], "enabled": True}, headers=h)
    again = admin.post("/api/rules/import/sigmahq", headers=h).json()
    assert (again["new_rules"], again["updated"], again["unchanged"]) == (0, 0, 1)
    rules = admin.get("/api/rules").json()
    assert [(r["rule_id"], r["enabled"]) for r in rules] == [(GOOD_ID, True)]


def test_non_admin_cannot_import_or_read_the_release(lab: dict[str, Any]) -> None:
    ana = lab["ana"]
    assert ana.post("/api/rules/import/sigmahq").status_code == 403
    assert ana.post("/api/rules/import/upload", content=PACKAGE).status_code == 403
    assert ana.get("/api/rules/sigmahq").status_code == 403
    assert lab["fake"].requests == []
    assert audit_rows(lab["db"]) == []


def test_upload_skips_unsafe_names_and_oversized_members(lab: dict[str, Any]) -> None:
    other = GOOD.replace(GOOD_ID, "77777777-7777-4777-8777-777777777777")
    zipped = make_zip(
        {
            "../../outside/escape.yml": GOOD,
            "/abs/root.yml": GOOD,
            "rules\\windows\\back.yml": GOOD,
            "rules/big.yml": "x" * (sigmahq.MAX_MEMBER_BYTES + 10),
            "rules/ok.yml": other,
        }
    )
    res = lab["admin"].post("/api/rules/import/upload", content=zipped, headers=lab["h"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["accepted"], body["skipped"], body["not_compiling"]) == (1, 4, 0)
    reasons = {r["path"]: r["reason"] for r in body["refusals"]}
    assert reasons["../../outside/escape.yml"] == "Unsafe file name in the archive"
    assert reasons["/abs/root.yml"] == "Unsafe file name in the archive"
    assert reasons["rules\\windows\\back.yml"] == "Unsafe file name in the archive"
    assert "larger than" in reasons["rules/big.yml"]
    assert lab["fake"].requests == []
    [(_, outcome, _, details)] = audit_rows(lab["db"])
    assert outcome == "success" and hashlib.sha256(zipped).hexdigest() in details


def test_upload_that_is_not_a_zip_or_too_large_is_refused(lab: dict[str, Any]) -> None:
    admin, h = lab["admin"], lab["h"]
    res = admin.post("/api/rules/import/upload", content=b"not a zip", headers=h)
    assert res.status_code == 400
    big = b"0" * (sigmahq.MAX_ZIP_BYTES + 1)
    assert admin.post("/api/rules/import/upload", content=big, headers=h).status_code == 413
    assert admin.get("/api/rules").json() == []


def test_member_whose_header_lies_about_its_size_is_capped() -> None:
    """A zip bomb: the reader stops at the per-member cap whatever the header says."""
    data = make_zip({"rules/bomb.yml": b"a" * (sigmahq.MAX_MEMBER_BYTES * 4)})
    walk = sigmahq.Walk()
    [member] = list(sigmahq.members(data, walk))
    assert member.data is None and "larger than" in member.reason


def test_redirect_off_github_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://files.example.com/x.zip"})

    monkeypatch.setattr(
        sigmahq, "default_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(RuleRejectedError, match="outside GitHub"):
        sigmahq.fetch_pinned()
