"""Microsoft 365 and Anthropic API sources end to end (ADR-0002, ADR-0015 row 10): add with
credentials, poll a fake service, route each record to its template, store, checkpoint,
back off, test before saving, rotate credentials, and never return or log a secret."""

import ipaddress
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

import app.alerts.net as net
from app.core.config import load_config
from app.main import create_app
from tests.fake_apis import CLIENT, TENANT, FakeApis

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)
BASE = "https://siem.example.internal"
FIX = Path(__file__).parents[1] / "fixtures" / "logs"


def sample(tid: str) -> list[dict[str, Any]]:
    lines = (FIX / tid / "sample.log").read_text("utf-8").splitlines()
    return [json.loads(x) for x in lines]


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Every service name resolves to one public (documentation range) address.
    monkeypatch.setattr(net, "_resolve", lambda host, port: [ipaddress.ip_address("203.0.113.80")])
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    fake = FakeApis()
    clock = Clock()
    app.state.ingest._clock = clock
    app.state.auth.clock = clock
    app.state.ingest.api_transport = fake.transport()
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup",
        json={"token": token, "username": "admin", "password": "correct horse battery"},
    ).json()["csrf_token"]
    return {
        "app": app,
        "admin": admin,
        "h": {"X-CSRF-Token": csrf},
        "fake": fake,
        "clock": clock,
        "db": tmp_path / "data" / "meta.sqlite",
    }


def rows(lab: dict[str, Any], sql: str) -> list[list[Any]]:
    res = lab["admin"].post("/api/query", json={"sql": sql}, headers=lab["h"])
    assert res.status_code == 200, res.text
    return list(res.json()["rows"])


def m365_body(**over: Any) -> dict[str, Any]:
    settings = {
        "tenant_id": TENANT,
        "client_id": CLIENT,
        "auth": "secret",
        "content_types": ["Audit.SharePoint", "Audit.General"],
        "graph": ["signins", "directory_audits"],
        "backfill_hours": 24,
    }
    return {
        "source_id": "m365",
        "format": "json",
        "kind": "m365",
        "template_id": "auto",
        "m365": settings | over,
        "credentials": {"client_secret": "m365-client-s3cret"},
    }


def seed_m365(fake: FakeApis) -> None:
    mgmt = sample("m365_management_activity")
    sp = [r for r in mgmt if r["Workload"] == "SharePoint"][:6]
    co = [r for r in mgmt if r["Workload"] == "Copilot"][:3]
    fake.blobs["Audit.SharePoint"] = [
        ("2026-10-14T17:10:00Z", sp[:3]),
        ("2026-10-14T17:30:00Z", sp[3:]),
    ]
    fake.blobs["Audit.General"] = [("2026-10-14T17:20:00Z", co)]
    fake.graph["auditLogs/signIns"] = sample("m365_signin")[:5]
    fake.graph["auditLogs/directoryAudits"] = sample("m365_directory_audit")[:4]


def add(lab: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    res: httpx.Response = lab["admin"].post("/api/sources", json=body, headers=lab["h"])
    return res


def test_m365_records_route_to_their_templates_with_raw_unchanged(lab: dict[str, Any]) -> None:
    seed_m365(lab["fake"])
    assert add(lab, m365_body()).status_code == 201
    written = lab["app"].state.ingest.run_once()
    assert written == 6 + 3 + 5 + 4
    got = rows(lab, "SELECT template_id, count(*) FROM events GROUP BY 1 ORDER BY 1")
    assert got == [
        ["m365_directory_audit", 4],
        ["m365_management_activity", 9],
        ["m365_signin", 5],
    ]
    (raw,) = rows(lab, "SELECT raw FROM events WHERE message = 'CopilotInteraction' LIMIT 1")[0]
    assert json.loads(raw)["Workload"] == "Copilot" and raw == json.dumps(
        json.loads(raw), separators=(",", ":"), ensure_ascii=False
    )
    assert lab["fake"].started == ["Audit.SharePoint", "Audit.General"]
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "reading" and status["warnings"] == []


def test_m365_polls_every_5_minutes_and_never_reads_a_record_twice(lab: dict[str, Any]) -> None:
    seed_m365(lab["fake"])
    add(lab, m365_body())
    ingest = lab["app"].state.ingest
    ingest.run_once()
    calls = len(lab["fake"].requests)
    lab["clock"].now = NOW + timedelta(minutes=2)
    assert ingest.run_once() == 0 and len(lab["fake"].requests) == calls  # too soon
    lab["clock"].now = NOW + timedelta(minutes=6)
    new = dict(sample("m365_management_activity")[0], Id="new-record")
    lab["fake"].blobs["Audit.SharePoint"].append(("2026-10-14T18:03:00Z", [new]))
    assert ingest.run_once() == 1
    assert rows(lab, "SELECT count(*) FROM events")[0][0] == 19
    # Subscriptions are started once, not every poll.
    assert lab["fake"].started == ["Audit.SharePoint", "Audit.General"]


def test_one_failing_feed_is_a_warning_and_the_rest_still_land(lab: dict[str, Any]) -> None:
    seed_m365(lab["fake"])
    lab["fake"].fail["/v1.0/auditLogs/signIns"] = httpx.Response(
        403, text='{"error":{"message":"... does not have premium license ..."}}'
    )
    add(lab, m365_body())
    assert lab["app"].state.ingest.run_once() == 6 + 3 + 4
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "reading"
    assert status["warnings"] == ["signins: Sign-in logs need Entra ID P1 or P2 in this tenant"]


def test_errors_back_off_and_retry_after_is_honored(lab: dict[str, Any]) -> None:
    add(lab, m365_body(content_types=["Audit.SharePoint"], graph=[]))
    lab["fake"].fail["/" + TENANT] = httpx.Response(
        401, json={"error": "invalid_client", "error_codes": [7000222]}
    )
    ingest = lab["app"].state.ingest
    ingest.run_once()
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "error" and "client secret has expired" in status["error"]
    assert status["retry_at"].startswith("2026-10-14T18:10")  # 5 minutes doubled
    calls = len(lab["fake"].requests)
    lab["clock"].now = NOW + timedelta(minutes=7)
    ingest.run_once()
    assert len(lab["fake"].requests) == calls  # still backing off
    lab["fake"].fail = {"/v1/organizations": httpx.Response(429, headers={"retry-after": "900"})}
    lab["fake"].fail.update({})
    add(
        lab,
        {
            "source_id": "claude",
            "format": "json",
            "kind": "anthropic",
            "template_id": "anthropic_reports",
            "anthropic": {"feeds": ["usage"]},
            "credentials": {"api_key": lab["fake"].api_key},
        },
    )
    ingest.run_once()
    claude = next(s for s in lab["admin"].get("/api/sources").json() if s["source_id"] == "claude")
    assert "asked to slow down" in claude["status"]["error"]
    assert claude["status"]["retry_at"].startswith("2026-10-14T18:22")  # 7 min + 900 s


def test_certificate_auth_signs_a_ps256_assertion_and_test_shows_thumbprint(
    lab: dict[str, Any],
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "siem-connector")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    settings = m365_body(auth="certificate", graph=["signins"])["m365"]
    creds = {"certificate_pem": cert_pem, "private_key_pem": key_pem}
    res = lab["admin"].post(
        "/api/sources/api/test",
        json={"kind": "m365", "m365": settings, "credentials": creds},
        headers=lab["h"],
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["thumbprint"] == cert.fingerprint(hashes.SHA1()).hex().upper()
    assert out["feeds"] == {"Management Activity API": "ok", "Graph signins": "ok"}
    form = lab["fake"].forms[-1]
    assert "client_secret" not in form
    header = jwt.get_unverified_header(form["client_assertion"][0])
    assert header["alg"] == "PS256" and "x5t#S256" in header
    claims = jwt.decode(
        form["client_assertion"][0],
        key.public_key(),
        algorithms=["PS256"],
        options={"verify_aud": False},
    )
    assert claims["iss"] == claims["sub"] == CLIENT
    # A key that does not belong to the certificate is refused before anything is saved.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad_key = other.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    body = m365_body(auth="certificate")
    body["credentials"] = {"certificate_pem": cert_pem, "private_key_pem": bad_key}
    bad = add(lab, body)
    assert bad.status_code == 400 and "does not belong" in bad.json()["detail"]
    assert lab["admin"].get("/api/sources").json() == []


def test_anthropic_feeds_land_and_compliance_reads_only_new_activities(
    lab: dict[str, Any],
) -> None:
    fake = lab["fake"]
    recs = [
        json.loads(x) for x in (FIX / "anthropic_reports" / "sample.log").read_text().splitlines()
    ]
    by = {
        f: [
            {k: v for k, v in r.items() if k != "feed"}
            for r in recs
            if r["feed"] == f"anthropic.{f}"
        ]
        for f in ("usage", "claude_code", "compliance_activities")
    }
    usage = by["usage"][:2]
    fake.anthropic["/v1/organizations/usage_report/messages"] = [
        {
            "data": [
                {
                    "starting_at": u["starting_at"],
                    "ending_at": u["ending_at"],
                    "results": [
                        {k: v for k, v in u.items() if k not in ("starting_at", "ending_at")}
                    ],
                }
                for u in usage
            ]
        }
    ]
    fake.anthropic["/v1/organizations/usage_report/claude_code"] = [
        {"data": by["claude_code"][:2]},
        {"data": by["claude_code"][2:3]},
    ]
    acts = sorted(by["compliance_activities"][:4], key=lambda a: a["created_at"], reverse=True)
    fake.anthropic["/v1/compliance/activities"] = [{"data": acts[:2]}, {"data": acts[2:]}]
    body = {
        "source_id": "claude",
        "format": "json",
        "kind": "anthropic",
        "template_id": "anthropic_reports",
        "anthropic": {
            "key_type": "admin",
            "feeds": ["usage", "claude_code", "compliance_activities"],
            "backfill_days": 1,
        },
        "credentials": {"api_key": fake.api_key},
    }
    assert add(lab, body).status_code == 201
    ingest = lab["app"].state.ingest
    # usage: 2 rows; claude_code: 1 finished day x 3 rows over two pages; compliance: 4.
    assert ingest.run_once() == 2 + 3 + 4
    got = rows(lab, "SELECT message, count(*) FROM events GROUP BY 1 ORDER BY 1")
    assert ["anthropic.usage", 2] in got and ["anthropic.claude_code", 3] in got
    lab["clock"].now = NOW + timedelta(minutes=6)
    # The same activities again plus one new one: only the new one is written.
    fake.anthropic["/v1/organizations/usage_report/claude_code"] = [{"data": []}]
    later = dict(acts[0], id="activity_new", created_at="2026-10-14T18:04:00Z")
    fake.anthropic["/v1/compliance/activities"] = [{"data": [later, *acts[:2]]}, {"data": acts[2:]}]
    written = ingest.run_once()
    newest = max(a["created_at"] for a in acts)
    compliance = [r for r in fake.requests if r.url.path == "/v1/compliance/activities"]
    assert f"created_at.gte={newest.replace(':', '%3A')}" in str(compliance[-1].url)
    assert written == 1  # no finished hour or day is due yet, and one activity is new
    assert rows(lab, "SELECT count(*) FROM events WHERE message NOT LIKE 'anthropic.%'")[0][0] == 5
    # Never chat content: no request touches the Compliance content endpoints.
    assert not [r for r in fake.requests if "/chats" in r.url.path or "/files" in r.url.path]


def test_secrets_never_returned_or_logged_and_settings_hidden_from_analysts(
    lab: dict[str, Any],
) -> None:
    seed_m365(lab["fake"])
    add(lab, m365_body())
    listed = lab["admin"].get("/api/sources").text
    assert "m365-client-s3cret" not in listed and TENANT in listed
    rotated = lab["admin"].put(
        "/api/sources/m365/credentials",
        json={"client_secret": "rotated-s3cret"},
        headers=lab["h"],
    )
    assert rotated.status_code == 204
    with sqlite3.connect(lab["db"]) as db:
        details = " ".join(r[0] for r in db.execute("SELECT detail FROM audit_log"))
        stored = db.execute("SELECT connector_secret_enc FROM sources").fetchone()[0]
    assert "s3cret" not in details and "s3cret" not in stored
    assert "source.credentials" in " ".join(
        r[0] for r in sqlite3.connect(lab["db"]).execute("SELECT action FROM audit_log")
    )
    lab["fake"].secret = "rotated-s3cret"
    assert lab["app"].state.ingest.run_once() > 0
    a = (
        lab["admin"]
        .post("/api/users", json={"username": "ana", "role": "analyst"}, headers=lab["h"])
        .json()
    )
    lab["admin"].post(
        "/api/account/password",
        json={"token": a["invite_token"], "password": "another long passphrase"},
    )
    gid = (
        lab["admin"].post("/api/groups", json={"name": "All"}, headers=lab["h"]).json()["group_id"]
    )
    lab["admin"].put(f"/api/groups/{gid}/sources", json={"source_ids": ["m365"]}, headers=lab["h"])
    lab["admin"].put(
        f"/api/groups/{gid}/members", json={"user_ids": [a["user"]["user_id"]]}, headers=lab["h"]
    )
    tok = (
        TestClient(lab["app"], base_url=BASE)
        .post(
            "/api/auth/login",
            json={"username": "ana", "password": "another long passphrase", "client": "cli"},
        )
        .json()["token"]
    )
    ana = TestClient(lab["app"], base_url=BASE, headers={"Authorization": f"Bearer {tok}"})
    (mine,) = ana.get("/api/sources").json()
    assert mine["m365"] is None and TENANT not in json.dumps(mine)


def test_bad_api_sources_are_refused(lab: dict[str, Any]) -> None:
    no_creds = m365_body()
    del no_creds["credentials"]
    assert add(lab, no_creds).status_code == 400
    wrong_key = {
        "source_id": "claude",
        "format": "json",
        "kind": "anthropic",
        "anthropic": {},
        "credentials": {"api_key": "not-a-key"},
    }
    assert add(lab, wrong_key).status_code == 400
    csv = m365_body()
    csv["format"] = "csv"
    csv["template_id"] = None
    assert add(lab, csv).status_code == 422
    mixed = m365_body()
    mixed["anthropic"] = {}
    assert add(lab, mixed).status_code == 422
    bad_tenant = m365_body(tenant_id="contoso.onmicrosoft.com")
    assert add(lab, bad_tenant).status_code == 422
