"""Who counts as a person on People and devices (owner review, 2026-11-06; D212).

A name is a person only with a successful sign-in, a known Microsoft 365 identity, or an
Identities link; a name with failed sign-ins and none of those is a targeted username,
listed apart with its attempts, sources, hosts, and where the attempts came from."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.core.timing import phase
from app.engine.duckdb import QueryScope
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.search.entities import entity_risk
from app.search.identity import IdentityMap
from app.search.targeted import Targeted, place
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer

ROOT = Path(__file__).resolve().parents[3]
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
# carol is linked by an administrator to her personal address (Identities).
IDENT = IdentityMap(domains=["example.com"], aliases={"carol": "carol@example.org"})

SPRAY = ["root", "ubuntu", "minecraft", "oracle"]


def _ssh(i: int, host: str, text: str) -> str:
    return f"<38>Oct 20 10:{i % 60:02d}:{i // 60:02d} {host} sshd[{100 + i}]: {text}"


SSHD = [
    _ssh(0, "web-01", "Accepted password for alice from 10.20.1.5 port 50000 ssh2"),
    _ssh(1, "web-01", "Accepted publickey for bob from 10.20.1.6 port 50001 ssh2"),
    _ssh(2, "web-01", "Failed password for bob from 10.20.1.6 port 50002 ssh2"),
    _ssh(3, "bastion", "Failed password for carol from 203.0.113.20 port 50003 ssh2"),
    _ssh(4, "bastion", "Failed password for dana from 198.51.100.4 port 50004 ssh2"),
    # Spraying from outside: invalid users and real-looking role names, and the
    # disconnects that follow (status 1, but a log off, not a sign-in).
    *[
        _ssh(10 + i, "bastion" if (i // 4) % 2 else "web-01",
             f"Failed password for {'invalid user ' if n == 'minecraft' else ''}{n}"
             f" from {'203.0.113.9' if i % 3 else '198.51.100.77'} port {40000 + i} ssh2")
        for i, n in enumerate(SPRAY * 6)
    ],
    _ssh(40, "bastion", "Connection closed by authenticating user root 203.0.113.9 port 4 [preauth]"),
    _ssh(41, "bastion", "Disconnected from invalid user oracle 203.0.113.9 port 5 [preauth]"),
]  # fmt: skip
MGMT = [
    json.dumps({
        "CreationTime": "2026-10-21T09:00:00", "Id": "id-1", "Operation": "FileDownloaded",
        "RecordType": 6, "UserId": "dana@example.com", "Workload": "SharePoint",
        "ResultStatus": "Succeeded", "ClientIP": "192.0.2.40",
    })
]  # fmt: skip


def _rows(template: str, lines: list[str], source: str) -> list[dict[str, Any]]:
    spec = parse_template((ROOT / "templates" / "starter" / f"{template}.yaml").read_text())
    norm = TemplateNormalizer(spec, template)
    out = []
    for x in lines:
        r = norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False))
        r["source_id"] = source
        out.append(r)
    return out


@pytest.fixture
def app(tmp_path: Path) -> Any:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "data")})
    app = create_app(config)
    LakeWriter(app.state.engine._lake).write(
        _rows("linux_sshd", SSHD, "lin") + _rows("m365_management_activity", MGMT, "m365")
    )
    return app


def _risk(app: Any, allowed: list[str] | None = None) -> tuple[set[str], dict[str, Targeted]]:
    ranked, _, _, spl = entity_risk(
        app.state.engine, app.state.meta, allowed, QueryScope(allowed, START, END), IDENT, None
    )
    return {r.value for r in ranked["user"]}, {t.value: t for t in spl.rows}


def test_spray_names_are_targeted_and_people_are_users(app: Any) -> None:
    users, targeted = _risk(app)
    assert {"alice", "bob", "carol@example.org", "dana@example.com"} <= users
    assert not set(SPRAY) & users
    assert set(targeted) == set(SPRAY)
    root = targeted["root"]
    assert root.attempts == 6  # the disconnect is neither an attempt nor a sign-in
    assert root.sources == ["lin"] and root.hosts == ["bastion", "web-01"]
    assert set(root.ips) == {"203.0.113.9", "198.51.100.77"}
    assert targeted["minecraft"].attempts == 6


def test_only_the_callers_sources_count(app: Any) -> None:
    users, targeted = _risk(app, ["m365"])
    assert targeted == {} and "root" not in users
    # Without the Microsoft 365 source, dana's only evidence is gone: she is targeted.
    users, targeted = _risk(app, ["lin"])
    assert "dana" in targeted and "dana" not in users and "alice" in users


def test_a_successful_sign_in_moves_a_name_to_users(app: Any) -> None:
    LakeWriter(app.state.engine._lake).write(
        _rows(
            "linux_sshd",
            [_ssh(50, "web-01", "Accepted password for oracle from 10.20.1.9 port 6 ssh2")],
            "lin",
        )
    )
    users, targeted = _risk(app)
    assert "oracle" in users and "oracle" not in targeted
    assert {"root", "ubuntu", "minecraft"} == set(targeted)


def test_places_from_enrichment_and_nothing_when_off() -> None:
    rows = [Targeted(value="root", attempts=9, ips={"203.0.113.9": 6, "198.51.100.77": 3})]
    place(rows, None)
    assert rows[0].countries == [] and rows[0].asns == []
    info = {
        "203.0.113.9": SimpleNamespace(country="NL", country_name="Netherlands", asn=64500, org="Example Net"),
        "198.51.100.77": SimpleNamespace(country="BR", country_name="Brazil", asn=64501, org=None),
    }  # fmt: skip
    place(rows, SimpleNamespace(enrich=lambda ips: {ip: info[ip] for ip in ips}))  # type: ignore[arg-type]
    assert [(p.label, p.attempts) for p in rows[0].countries] == [("Netherlands", 6), ("Brazil", 3)]
    assert [p.label for p in rows[0].asns] == ["AS64500 Example Net", "AS64501"]


def test_api_lists_targeted_without_addresses(app: Any) -> None:
    app.state.identities.set_domains(["example.com"], "admin")
    app.state.identities.set_alias("carol", "carol@example.org", "admin")
    client = TestClient(app)
    res = client.get("/api/entities/risk", params={"start": "2026-10-01T00:00:00Z"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["targeted_total"] == 4
    assert {t["value"] for t in body["targeted"]} == set(SPRAY)
    assert "ips" not in body["targeted"][0] and body["targeted"][0]["countries"] == []
    assert not set(SPRAY) & {u["value"] for u in body["users"]}


PHASES = (
    "access", "identities", "rule_matches", "signals_seen", "signals_mail_rules",
    "signals_new_mcp", "alerts", "flagged_runs", "people_split", "people_attackers",
    "scoring", "enrichment", "audit",
)  # fmt: skip


def test_server_timing_names_each_phase_and_no_data(app: Any) -> None:
    """Review item 7: the page's response says where its time went, by fixed names."""
    res = TestClient(app).get("/api/entities/risk", params={"start": "2026-10-01T00:00:00Z"})
    assert res.status_code == 200, res.text
    header = res.headers["Server-Timing"]
    metrics = dict(m.split(";", 1) for m in header.split(", "))
    for name in PHASES:
        assert re.fullmatch(r"dur=\d+\.\d", metrics[name]), (name, header)
    assert {"db", "total"} <= set(metrics)
    # Only fixed names and numbers: no username, address, host, or source id.
    for value in [*SPRAY, "alice", "203.0.113.9", "bastion", "lin", "m365", "example"]:
        assert value not in header


def test_a_phase_name_is_a_fixed_word() -> None:
    with pytest.raises(ValueError):
        with phase("root;dur=1"):
            pass
    with phase("fine_name"):  # no request: nothing recorded, no error
        pass
