"""People and devices ranking (owner, 2026-11-03; D195): everyone seen in the range is
listed, even with no rule match; the score is the sum of parts each shown on its own
(failed sign-ins, risky inbox rules, app consents, AI watch flags, attack hits, alerts);
ties go to the busier entity; only the caller's sources count."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.config import load_config
from app.engine.duckdb import QueryScope
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.search.entities import entity_risk
from app.search.identity import IdentityMap
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer

ROOT = Path(__file__).resolve().parents[3]
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)


def _hook(t: str, event: str, session: str, host: str, **attr: Any) -> str:
    return json.dumps({
        "signal": "log", "time": t, "service": "claude-hooks", "event": event,
        "attr": {"event_name": event, "session_id": session, **attr},
        "body": event, "resource": {"service_name": "claude-hooks", "host_name": host},
        "content": "dropped",
    })  # fmt: skip


def _mgmt(t: str, op: str, user: str, **extra: Any) -> str:
    return json.dumps({
        "CreationTime": t, "Id": f"id-{op}-{t}", "Operation": op, "RecordType": 1,
        "UserId": user, "Workload": "Exchange", "ResultStatus": "True",
        "ClientIP": "203.0.113.40", **extra,
    })  # fmt: skip


SSHD = [
    # 30 failures on bastion from an outside address, and a quiet internal login on db-01.
    *[f"<38>Oct 20 10:{i:02d}:00 bastion sshd[1]: Failed password for root from 203.0.113.9"
      f" port 4{i:03d} ssh2" for i in range(30)],
    "<38>Oct 20 11:00:00 db-01 sshd[2]: Accepted publickey for jordan from 10.20.2.14 port 5 ssh2",
]  # fmt: skip
HOOKS = [
    _hook("2026-10-20T10:00:00Z", "claude_hooks.pre_tool_use", "s1", "ws-alpha",
          tool_name="Bash", claude_account_email="dana@example.org"),
    _hook("2026-10-20T10:00:01Z", "claude_hooks.post_tool_use_failure", "s1", "ws-alpha",
          tool_name="Bash", claude_account_email="dana@example.org"),
    _hook("2026-10-20T10:01:00Z", "claude_hooks.pre_tool_use", "s1", "ws-alpha",
          tool_name="mcp__wiki__search", mcp_server_name="wiki", mcp_tool_name="search",
          claude_account_email="dana@example.org"),
]  # fmt: skip
MGMT = [
    _mgmt("2026-10-21T09:00:00", "New-InboxRule", "erin@example.com",
          Parameters=[{"Name": "Name", "Value": "x"}, {"Name": "MoveToFolder", "Value": "RSS Feeds"}]),
    _mgmt("2026-10-21T09:05:00", "Consent to application.", "erin@example.com",
          Workload="AzureActiveDirectory"),
]  # fmt: skip


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("rank")
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data")})
    app = create_app(config)
    rows = []
    for template, lines, source in (
        ("linux_sshd", SSHD, "lin"), ("claude_hooks", HOOKS, "hooks"),
        ("m365_management_activity", MGMT, "m365"),
    ):  # fmt: skip
        spec = parse_template((ROOT / "templates" / "starter" / f"{template}.yaml").read_text())
        norm = TemplateNormalizer(spec, template)
        for x in lines:
            r = norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False))
            r["source_id"] = source
            rows.append(r)
    LakeWriter(app.state.engine._lake).write(rows)
    app.state.alert_items.raise_item(
        "ai_watch", "Personal account", "Personal Claude account on ws-alpha",
        sources=["hooks"], devices=["ws-alpha"],
    )  # fmt: skip
    return app


def _rank(app: Any, allowed: list[str] | None = None) -> dict[str, Any]:
    ranked, _, _, _ = entity_risk(
        app.state.engine, app.state.meta, allowed, QueryScope(allowed, START, END),
        IdentityMap(domains=["example.com"]), app.state.ai_usage,
    )  # fmt: skip
    return {f"{r.kind}:{r.value}": r for rs in ranked.values() for r in rs}


def test_everyone_seen_is_listed_and_ranked_by_parts(app: Any) -> None:
    by = _rank(app)
    # No rule ran; a quiet host is still listed, scored 0, ordered by its events.
    assert by["host:db-01"].score == 0 and by["host:db-01"].events == 1
    bastion = by["host:bastion"]
    assert bastion.failed_signins == 30 and bastion.attacks == 30
    assert bastion.parts == {"failed_signins": 25, "attacks": 25}  # each capped
    assert bastion.score == 50
    attacker = by["ip:203.0.113.9"]
    assert attacker.attacks == 30 and attacker.score == sum(attacker.parts.values())


def test_ai_flags_and_alerts(app: Any) -> None:
    by = _rank(app)
    ws = by["host:ws-alpha"]
    assert set(ws.ai_flags) == {"personal_account", "blocked_calls", "new_mcp"}
    assert ws.alerts == 1 and ws.parts["alerts"] == 5 and ws.parts["ai_flags"] == 9
    dana = by["user:dana@example.org"]
    assert {"personal_account", "new_mcp"} <= set(dana.ai_flags)


def test_mail_rules_and_consents(app: Any) -> None:
    erin = _rank(app)["user:erin@example.com"]
    assert erin.mail_rules == 1 and erin.consents == 1
    assert erin.parts["mail_rules"] == 5 and erin.parts["consents"] == 3


def test_only_the_callers_sources_count(app: Any) -> None:
    by = _rank(app, ["lin"])
    assert "host:ws-alpha" not in by and "user:erin@example.com" not in by
    assert by["host:bastion"].alerts == 0
