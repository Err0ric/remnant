"""F66: Microsoft 365 records fill the resource, failure-reason, permission, and
correlation columns (D121); a lake file written before those columns existed reads them
as NULL; and the Sources page learns which template mappings changed and when (release
safety)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.engine.duckdb import QueryScope
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer
from tests.integration.test_schedules import make_lab

STARTER = Path(__file__).resolve().parents[3] / "templates" / "starter"


def _rows(template_id: str, test_names: list[str], source: str) -> list[dict[str, Any]]:
    t = parse_template((STARTER / f"{template_id}.yaml").read_text())
    norm = TemplateNormalizer(t, source)
    by_name = {x.name: x for x in t.tests}
    return [
        norm.normalize(DecodedLine(text=by_name[n].input, bytes_invalid=False, truncated=False))
        for n in test_names
    ]


def test_a_failed_consent_from_both_feeds_fills_the_same_columns(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine = lab["app"].state.engine
    graph = _rows(
        "m365_directory_audit",
        ["a blocked consent (Entra writes Unknown as the app name)"],
        "m365_graph",
    )
    mgmt = _rows(
        "m365_management_activity",
        ["the same blocked consent from the Management API"],
        "m365_mgmt",
    )
    LakeWriter(engine._lake).write(graph + mgmt)
    rows = engine.run(
        "SELECT source_id, status_id, status_detail, resource_name, resource_uid, privileges,"
        " metadata_correlation_uid, json_extract_string(unmapped, '$.consent_type')"
        " FROM events WHERE message ILIKE 'Consent to application%' ORDER BY source_id",
        QueryScope(None),
    ).rows
    assert [r[0] for r in rows] == ["m365_graph", "m365_mgmt"]
    for r in rows:
        assert r[1] == 2 and r[2] == "Microsoft.Online.Security.AuthorizationException"
        assert r[3] is None  # Entra's "Unknown" is no name
        assert r[4] == "0a1b2c3d-0000-4000-8000-0000000000a1"
        assert r[5] == "openid profile email offline_access User.Read" and r[7] == "user"
    assert rows[0][6] == rows[1][6]  # one operation, one correlation id in both feeds


def test_files_written_before_the_new_columns_read_them_as_null(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine = lab["app"].state.engine
    old = engine._lake / "source=legacy" / "day=2026-10-01"
    old.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "event_id": ["e1"],
                "source_id": ["legacy"],
                "template_id": ["t"],
                "template_version": ["1"],
                "time": pa.array(
                    [datetime(2026, 10, 1, 12, tzinfo=UTC)], pa.timestamp("us", "UTC")
                ),
                "time_observed": pa.array(
                    [datetime(2026, 10, 1, 12, tzinfo=UTC)], pa.timestamp("us", "UTC")
                ),
                "message": ["old"],
                "raw": ["old"],
                "raw_bytes_invalid": [False],
                "parse_status": ["ok"],
                "classification": ["local_only"],
                "owner_id": ["system"],
            }
        ),
        old / "part-0.parquet",
    )
    rows = engine.run(
        "SELECT message, resource_name, privileges, status_detail FROM events"
        " WHERE source_id = 'legacy'",
        QueryScope(["legacy"]),
    ).rows
    assert rows == [["old", None, None, None]]


def test_the_sources_page_learns_which_mappings_changed_and_what_to_check(
    tmp_path: Path,
) -> None:
    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    res = admin.get("/api/templates/changes")
    assert res.status_code == 200, res.text
    found = {(c["template_id"], c["version"]): c for c in res.json()}
    c = found[("m365_directory_audit", "1.1.0")]
    assert c["current"] is True and c["since"] and c["fields"] == [] and c["affected"] == []
    # A saved search that filters on a changed column is listed for review.
    reg = lab["app"].state.templates
    t = reg.get("m365_signin")
    changed = t.model_copy(
        update={"changes": [t.changes[0].model_copy(update={"fields": ["status_id"]})]}
    )
    reg._templates["m365_signin"] = changed  # as if the template declared status_id changed
    made = admin.post(
        "/api/searches",
        json={
            "id": "failed_signins",
            "name": "Failed sign-ins",
            "sql": "SELECT * FROM events WHERE status_id = 2",
        },
        headers=h,
    )
    assert made.status_code == 201, made.text
    c = {(x["template_id"], x["version"]): x for x in admin.get("/api/templates/changes").json()}[
        ("m365_signin", "1.1.0")
    ]
    assert [(a["kind"], a["name"], a["fields"]) for a in c["affected"]] == [
        ("saved search", "Failed sign-ins", ["status_id"])
    ]
    assert lab["ana"].get("/api/templates/changes").status_code == 403
    assert json.dumps(c)  # serializable as sent
