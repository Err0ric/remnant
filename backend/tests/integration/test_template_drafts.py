"""Template drafts end to end: create, edit, preview, approve, replace, remove (ADR-0005)."""

import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

LOGS = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def approve(client: Any, template_id: str) -> Any:
    """Approve the saved draft the way the UI does: preview it, then name what was reviewed."""
    url = f"/api/templates/drafts/{template_id}"
    reviewed = client.post(f"{url}/preview", json={}).json()["sha256"]
    return client.post(f"{url}/approve", json={"sha256": reviewed})


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs" / "bastion"
    logs.mkdir(parents=True)
    shutil.copy(LOGS / "linux_sshd" / "sample.log", logs / "auth.log")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path / "logs"),
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    return {"app": app, "c": TestClient(app), "logs": logs, "tmp": tmp_path}


def _db(lab: dict[str, Any]) -> sqlite3.Connection:
    return sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")


def _audit(lab: dict[str, Any]) -> list[tuple[str, str]]:
    return (
        _db(lab)
        .execute(
            "SELECT action, outcome FROM audit_log WHERE action LIKE 'template.%' ORDER BY audit_id"
        )
        .fetchall()
    )


def _create(lab: dict[str, Any], **body: Any) -> Any:
    return lab["c"].post("/api/templates/drafts", json=body)


def _file_sample(lab: dict[str, Any]) -> dict[str, str]:
    return {"kind": "file", "path": str(lab["logs"]), "glob": "*.log"}


def test_copy_preview_approve_and_use(lab: dict[str, Any]) -> None:
    res = _create(
        lab, template_id="bastion_sshd", from_template="linux_sshd", sample=_file_sample(lab)
    )
    assert res.status_code == 201, res.text
    draft = res.json()
    assert yaml.safe_load(draft["yaml"])["id"] == "bastion_sshd"
    assert draft["sample"]["kind"] == "file"
    # The draft is inert: not offered to sources yet.
    ids = [t["id"] for t in lab["c"].get("/api/templates").json()]
    assert "bastion_sshd" not in ids

    preview = lab["c"].post("/api/templates/drafts/bastion_sshd/preview", json={}).json()
    assert preview["valid"] and preview["approvable"], preview["errors"]
    assert all(t["passed"] for t in preview["tests"])
    assert preview["lines"] >= 50 and preview["ok"] >= 0.9 * preview["lines"]
    first = preview["rows"][0]
    assert first["class_uid"] == 3002 and "actor_user_name" in first["fields"]

    approved = approve(lab["c"], "bastion_sshd")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["version"] == "1.0.0" and len(body["sha256"]) == 64
    assert lab["c"].get("/api/templates/drafts").json() == []
    assert "bastion_sshd" in [t["id"] for t in lab["c"].get("/api/templates").json()]
    src = {
        "source_id": "bastion",
        "format": "syslog",
        "path": str(lab["logs"]),
        "template_id": "bastion_sshd",
    }
    assert lab["c"].post("/api/sources", json=src).status_code == 201
    assert lab["app"].state.ingest.run_once() > 50
    assert _audit(lab) == [
        ("template.draft_create", "success"),
        ("template.approve", "success"),
    ]
    (row,) = _db(lab).execute("SELECT template_id, version, sha256 FROM template_approvals")
    assert row[0] == "bastion_sshd" and row[2] == body["sha256"]


def test_blank_skeleton_from_pasted_lines_is_approvable(lab: dict[str, Any]) -> None:
    text = "widget started\nwidget stopped\n\nwidget crashed: code=7\n"
    res = _create(lab, template_id="widget_app", sample={"kind": "pasted", "text": text})
    assert res.status_code == 201, res.text
    assert res.json()["sample"] == {"kind": "pasted", "path": None, "glob": None, "lines": 3}
    preview = lab["c"].post("/api/templates/drafts/widget_app/preview", json={}).json()
    assert preview["approvable"], preview["errors"]
    assert [r["fields"].get("message") for r in preview["rows"]] == [
        "widget started",
        "widget stopped",
        "widget crashed: code=7",
    ]
    assert approve(lab["c"], "widget_app").status_code == 200


def test_skeleton_names_the_sample_tag_so_automatic_sources_use_it(lab: dict[str, Any]) -> None:
    """ADR-0012: once approved, a draft for one program is picked by Automatic sources."""
    text = "".join(
        f"<134>Oct  9 20:0{i}:00 fw-edge filterlog: action=block src=192.0.2.{i} dport=22\n"
        for i in range(5)
    )
    _create(lab, template_id="edge_fw", sample={"kind": "pasted", "text": text})
    yaml_text = lab["c"].get("/api/templates/drafts/edge_fw").json()["yaml"]
    assert "app_name:\n  - filterlog" in yaml_text
    assert approve(lab["c"], "edge_fw").status_code == 200
    auto = lab["app"].state.templates.get("edge_fw")
    assert auto is not None and auto.match.app_name == ["filterlog"]


def test_invalid_yaml_previews_errors_and_cannot_be_approved(lab: dict[str, Any]) -> None:
    _create(lab, template_id="broken_one", sample={"kind": "pasted", "text": "x\n"})
    bad = "schema_version: 1\nid: broken_one\nname: Broken\n"
    assert lab["c"].put("/api/templates/drafts/broken_one", json={"yaml": bad}).status_code == 200
    preview = lab["c"].post("/api/templates/drafts/broken_one/preview", json={}).json()
    assert not preview["valid"] and preview["errors"]
    res = approve(lab["c"], "broken_one")
    assert res.status_code == 400
    assert ("template.approve", "failure") in _audit(lab)
    # Unsaved edits can be previewed without touching the stored draft.
    good = lab["c"].get("/api/templates/drafts/broken_one").json()["yaml"]
    assert good == bad


def test_ids_versions_and_starter_names(lab: dict[str, Any]) -> None:
    assert _create(lab, template_id="linux_sshd").status_code == 409
    assert _create(lab, template_id="Bad-Id").status_code in (400, 422)
    _create(lab, template_id="my_app", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    text = lab["c"].get("/api/templates/drafts/my_app").json()["yaml"]
    renamed = text.replace("id: my_app", "id: other_app")
    preview = lab["c"].post("/api/templates/drafts/my_app/preview", json={"yaml": renamed}).json()
    assert not preview["approvable"] and any("other_app" in e for e in preview["errors"])
    assert approve(lab["c"], "my_app").status_code == 200

    # Replacing an approved template needs a higher version.
    _create(lab, template_id="my_app", from_template="my_app")
    preview = lab["c"].post("/api/templates/drafts/my_app/preview", json={}).json()
    assert not preview["approvable"] and any("raise the version" in e for e in preview["errors"])
    assert lab["c"].get("/api/templates/drafts/my_app").json()["replaces_version"] == "0.1.0"
    bumped = (
        lab["c"]
        .get("/api/templates/drafts/my_app")
        .json()["yaml"]
        .replace("version: 0.1.0", "version: 0.2.0")
    )
    lab["c"].put("/api/templates/drafts/my_app", json={"yaml": bumped})
    assert approve(lab["c"], "my_app").status_code == 200
    versions = [r[0] for r in _db(lab).execute("SELECT version FROM template_approvals")]
    assert versions == ["0.1.0", "0.2.0"]


def test_templates_in_use_cannot_be_removed(lab: dict[str, Any]) -> None:
    _create(lab, template_id="in_use", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    approve(lab["c"], "in_use")
    src = {"source_id": "s1", "format": "syslog", "path": str(lab["logs"]), "template_id": "in_use"}
    lab["c"].post("/api/sources", json=src)
    assert lab["c"].delete("/api/templates/in_use").status_code == 409
    assert lab["c"].delete("/api/templates/linux_sshd").status_code == 409
    lab["c"].delete("/api/sources/s1")
    assert lab["c"].delete("/api/templates/in_use").status_code == 204
    assert "in_use" not in [t["id"] for t in lab["c"].get("/api/templates").json()]


def test_samples_are_bounded_and_inside_the_roots(lab: dict[str, Any]) -> None:
    too_many = "\n".join(f"line {i}" for i in range(201))
    assert (
        _create(lab, template_id="big", sample={"kind": "pasted", "text": too_many}).status_code
        == 400
    )
    outside = {"kind": "file", "path": str(lab["tmp"])}
    assert _create(lab, template_id="outside", sample=outside).status_code == 400
    assert lab["c"].get("/api/templates/drafts").json() == []


def test_catastrophic_regex_is_bounded(lab: dict[str, Any]) -> None:
    _create(lab, template_id="slow_one", sample={"kind": "pasted", "text": "a" * 5000 + "!\n"})
    text = lab["c"].get("/api/templates/drafts/slow_one").json()["yaml"]
    text = text.replace("^(?P<text>.+)$", "^(?P<text>(a+)+)$")
    started = time.monotonic()
    preview = lab["c"].post("/api/templates/drafts/slow_one/preview", json={"yaml": text}).json()
    assert time.monotonic() - started < 10
    assert preview["valid"]


def test_approvals_are_append_only(lab: dict[str, Any]) -> None:
    _create(lab, template_id="pinned", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    approve(lab["c"], "pinned")
    db = _db(lab)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE template_approvals SET approved_by = 'someone'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM template_approvals")


def test_yaml_aliases_are_refused(lab: dict[str, Any]) -> None:
    _create(lab, template_id="bomb", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    bomb = "a: &a [x, x, x, x, x, x, x, x]\n" + "".join(
        f"{c}: &{c} [*{p}, *{p}, *{p}, *{p}, *{p}, *{p}, *{p}, *{p}]\n"
        for p, c in zip("abcdefghi", "bcdefghij", strict=True)
    )
    started = time.monotonic()
    preview = lab["c"].post("/api/templates/drafts/bomb/preview", json={"yaml": bomb}).json()
    assert time.monotonic() - started < 5
    assert not preview["valid"] and "aliases" in preview["errors"][0]


def test_skeleton_skips_lines_it_cannot_parse(lab: dict[str, Any]) -> None:
    text = "<13>Oct  9 20:41:12 host app[1]:\nreal line one\nreal line two\n"
    _create(lab, template_id="header_only", sample={"kind": "pasted", "text": text})
    preview = lab["c"].post("/api/templates/drafts/header_only/preview", json={}).json()
    assert preview["approvable"], preview["errors"]


def test_copy_handles_commented_id_lines(lab: dict[str, Any]) -> None:
    _create(lab, template_id="mine", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    text = lab["c"].get("/api/templates/drafts/mine").json()["yaml"]
    lab["c"].put(
        "/api/templates/drafts/mine", json={"yaml": text.replace("id: mine", "id: 'mine'  # x")}
    )
    assert approve(lab["c"], "mine").status_code == 200
    res = _create(lab, template_id="mine_copy", from_template="mine")
    assert res.status_code == 201, res.text
    assert yaml.safe_load(res.json()["yaml"])["id"] == "mine_copy"


def test_unreadable_approved_file_blocks_replacement(lab: dict[str, Any]) -> None:
    _create(lab, template_id="fragile", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    approve(lab["c"], "fragile")
    (lab["tmp"] / "data" / "templates" / "fragile.yaml").write_text("not: [valid")
    lab["app"].state.templates.reload()
    _create(lab, template_id="fragile", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    preview = lab["c"].post("/api/templates/drafts/fragile/preview", json={}).json()
    assert not preview["approvable"] and any("cannot be read" in e for e in preview["errors"])


def test_failed_changes_are_audited(lab: dict[str, Any]) -> None:
    assert _create(lab, template_id="linux_sshd").status_code == 409
    assert lab["c"].delete("/api/templates/drafts/nope").status_code == 404
    assert _audit(lab) == [
        ("template.draft_create", "failure"),
        ("template.draft_delete", "failure"),
    ]


def test_approval_names_the_bytes_that_were_reviewed(lab: dict[str, Any]) -> None:
    """A save landing between an admin's preview and approval (another admin, or an AI
    draft) must not be approved under that admin's name."""
    text = "widget started\nwidget stopped\nwidget crashed: code=7\n"
    _create(lab, template_id="widget_app", sample={"kind": "pasted", "text": text})
    url = "/api/templates/drafts/widget_app"
    reviewed = lab["c"].post(f"{url}/preview", json={}).json()
    saved = lab["c"].get(url).json()["yaml"]
    changed = saved.replace("version: 0.1.0", "version: 0.1.1")
    assert changed != saved
    assert lab["c"].put(url, json={"yaml": changed}).status_code == 200
    stale = lab["c"].post(f"{url}/approve", json={"sha256": reviewed["sha256"]})
    assert stale.status_code == 409 and "Preview it again" in stale.json()["detail"]
    assert lab["c"].post(f"{url}/approve", json={}).status_code == 422  # must name it
    assert approve(lab["c"], "widget_app").status_code == 200  # after a fresh preview


def test_a_template_cannot_be_removed_while_a_source_is_being_added_with_it(
    lab: dict[str, Any],
) -> None:
    import threading

    from app.ingest.sources import SourceConfig

    _create(lab, template_id="racy", sample={"kind": "pasted", "text": "a\nb\nc\n"})
    approve(lab["c"], "racy")
    app = lab["c"].app
    drafts, sources = app.state.drafts, app.state.sources
    inside, release = threading.Event(), threading.Event()
    outcome: list[str] = []

    def add_slowly() -> SourceConfig:
        inside.set()
        release.wait(5)
        cfg = SourceConfig(
            source_id="s9", format="syslog", path=str(lab["logs"]), template_id="racy"
        )
        return sources.add(cfg)

    adder = threading.Thread(target=lambda: drafts.with_template("racy", add_slowly))
    adder.start()
    assert inside.wait(5)

    def remove() -> None:
        try:
            drafts.delete_template("racy")
            outcome.append("deleted")
        except Exception as exc:  # the expected refusal
            outcome.append(type(exc).__name__)

    remover = threading.Thread(target=remove)
    remover.start()
    remover.join(0.3)
    assert remover.is_alive()  # waits for the add instead of deleting underneath it
    release.set()
    adder.join(5)
    remover.join(5)
    assert outcome == ["ConflictError"]  # the source now uses it
