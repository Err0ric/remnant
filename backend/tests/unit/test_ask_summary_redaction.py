# ruff: noqa: F811  # `lab` is the shared pytest fixture, used by name as a parameter
"""The summary's column stats never carry an identifying value past the redactor
(ADR-0010, D36, D270): whatever the summary sends, built from any row of the result and
not only the rows sent, reaches a cloud model with every address, user, and host name
hidden, also when the query renamed or wrapped the column (`AS who`, `lower(...)`, a
concatenation), which the redactor cannot know by name. The stats list no text value at
all. Local providers are never redacted and get the same stats."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from typing import Any

from app.llm.ask_summary import summarize
from app.llm.prompt_files import PROMPT_DIR
from app.llm.provider import ProviderResponse
from app.llm.redact import COLUMN_KINDS
from app.search.ask_summary import ANSWER_ROWS, sample
from tests.unit.test_gate_redaction import opt_in, sent_text
from tests.unit.test_llm_gate import CLOUD_URL, LOCAL_URL, Lab, lab  # noqa: F401  # fixture

LONG = "x" * 70  # host names longer than any value cut
# Identifying values under names the redactor does not know, as model SQL may write them.
RENAMED = ["who", "lower(actor_user_name)", "actor_user_name || '@' || device_hostname"]


def _rows() -> tuple[list[str], list[list[Any]]]:
    # The renamed columns and free text first: a sample keeps 12 columns.
    cols = ["event_id", "time", *RENAMED, "message", "detail", "action", *COLUMN_KINDS]
    rows = []
    for i in range(300):
        late = i >= ANSWER_ROWS  # seen only in rows that are not sent
        user = ("alice" if i % 2 else f"erin{i}@example.com") if late else "bob"
        host = f"laptop-alice-{LONG}.example" if late else "ws-bob.example"
        src = f"198.51.100.{i % 200}"
        values = {
            "src_endpoint_ip": src,
            "dst_endpoint_ip": "203.0.113.7" if late else "192.0.2.1",
            "device_ip": f"2001:db8::{i:x}",
            "actor_user_name": user,
            "device_hostname": host,
            "src_endpoint_hostname": f"src-{LONG}-{i % 3}.example.net" if late else "src.example",
            "dst_endpoint_hostname": f"dst-{LONG}.example.org" if late else "dst.example",
        }
        rows.append(
            [
                f"0190a1b2-0000-7000-8000-{i:012d}",
                datetime(2026, 10, 10, tzinfo=UTC) + timedelta(minutes=i),
                user,
                user.lower(),
                f"{user}@{host}",
                f"login by {user} from {src} on {host}",
                f"seen on {values['dst_endpoint_hostname']}",
                "allow" if i % 3 else "deny",
                *values.values(),
            ]
        )
    return cols, rows


def _unsent(cols: list[str], rows: list[list[Any]]) -> set[str]:
    """Every identifying value of the rows not sent, under any column name."""
    at = [cols.index(c) for c in [*COLUMN_KINDS, *RENAMED, "message", "detail"]]
    return {str(r[i]).lower() for r in rows[ANSWER_ROWS:] for i in at}


def _summarize(lab: Lab, pid: str) -> dict[str, Any]:
    shutil.copy(PROMPT_DIR / "ask_answer.v2.md", lab.gate._prompt_dir / "ask_answer.v2.md")
    cols, rows = _rows()
    s = sample(cols, rows, False)
    assert s is not None
    first = s.rows[0][0]
    claims = [{"text": "One sign-in.", "event_ids": [first]}]
    lab.reply[0] = ProviderResponse(text=json.dumps({"claims": claims}), model="m")
    got = summarize(lab.gate, "u1", pid, "who signed in?", s, ["fw_edge"])
    assert got.claims == [("One sign-in.", [first])]
    sent = json.loads(lab.fakes[-1].seen[-1]["messages"][-1].content)["data"]
    return sent  # type: ignore[no-any-return]  # JSON object


def test_no_identifying_value_from_any_row_reaches_a_cloud_model(lab: Lab) -> None:
    pid = opt_in(lab, CLOUD_URL)
    sent = _summarize(lab, pid)
    cols, rows = _rows()
    text = sent_text(lab).lower()
    leaked = sorted(v for v in _unsent(cols, rows) if v in text)
    assert leaked == [], f"identifying values sent in plain text: {leaked[:5]}"
    assert "alice" not in text and "erin" not in text and LONG[:20] not in text
    # The stats still say something: counts for every column, ranges for times.
    stats = sent["column_stats"]
    assert stats["actor_user_name"] == {"values": 300, "distinct": 147}  # bob, alice, 145 erins
    assert stats["who"] == stats["actor_user_name"] and stats["action"]["distinct"] == 2
    assert stats["time"]["min"].startswith("2026-10-10T00:00")
    assert all(set(stats[c]) == {"values", "distinct"} for c in [*RENAMED, "message", "action"])


def test_a_local_model_is_not_redacted_and_gets_the_same_stats(lab: Lab) -> None:
    pid = opt_in(lab, LOCAL_URL)
    sent = _summarize(lab, pid)
    text = sent_text(lab)
    assert "ws-bob.example" in text and "192.0.2.1" in text  # the sent rows, as they are
    assert sent["column_stats"] == _summarize_stats()


def _summarize_stats() -> dict[str, Any]:
    cols, rows = _rows()
    s = sample(cols, rows, False)
    assert s is not None
    return json.loads(json.dumps(s.stats, default=str))  # type: ignore[no-any-return]  # JSON
