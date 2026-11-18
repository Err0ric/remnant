"""A library query's own words for no rows (D274; owner, 2026-11-17, P3): plain text from
the pack, checked at load, used by Ask's headline and counted line in place of the
generic empty text."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.errors import ConfigError
from app.search.ask_summary import counted_line, headline
from app.search.library import LIBRARY_DIR, LibraryQuery, load, load_dir

BASE = {"id": "q", "name": "Q", "group": "G", "why": "w", "normal": "n", "sql": "SELECT 1"}
NO_LEASE = "No DHCP lease for this address in the range. It may be a static address."


def test_who_had_ip_says_there_is_no_lease() -> None:
    (pack,) = [p for p in load_dir(LIBRARY_DIR) if p.id == "paloalto"]
    (q,) = [q for q in pack.queries if q.id == "who_had_ip"]
    assert q.empty == NO_LEASE
    assert pack.version == "1.2.0"


def test_the_text_is_optional_and_trimmed() -> None:
    assert LibraryQuery.model_validate(BASE).empty is None
    assert LibraryQuery.model_validate({**BASE, "empty": "  Nothing.  "}).empty == "Nothing."


@pytest.mark.parametrize(
    "text",
    [
        "x" * 161,  # at most 160 characters
        "",
        "   ",
        "Two\nlines",
        "No <b>lease</b>",
        "No lease for {first.ip}",  # not a template
        "See [the docs](https://example.com)",
        "A *bold* claim",
        "A `code` span",
        "A tab\there",
        "Line\u2028separator",
        "Paragraph\u2029separator",
        "Next\x85line",
        "An _emphasised_ word",
        "A ~~struck~~ word",
    ],
)
def test_the_text_is_plain_and_short(text: str) -> None:
    with pytest.raises(ValidationError):
        LibraryQuery.model_validate({**BASE, "empty": text})


PACK = """schema_version: 1
id: mine
name: Mine
version: 1.0.0
queries:
- id: q
  name: Q
  group: G
  why: w
  normal: n
  sql: SELECT 1 AS n
  empty: {empty}
"""


def test_a_user_pack_may_say_it(tmp_path: Path) -> None:
    """D266 limits builtins in other packs, not text: a user pack with `empty` loads."""
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "pack.yaml").write_text(PACK.format(empty="Nobody signed in."))
    (pack,) = load_dir(tmp_path)
    assert pack.queries[0].empty == "Nobody signed in."
    (tmp_path / "mine" / "pack.yaml").write_text(PACK.format(empty="'<script>x</script>'"))
    with pytest.raises(ConfigError):
        load(tmp_path / "mine" / "pack.yaml")
    assert load_dir(tmp_path) == []  # refused at load, logged, left out


def test_ask_uses_it_for_no_rows_only() -> None:
    assert headline(["kind"], [], False, None, None, NO_LEASE) == NO_LEASE
    assert headline(["kind"], [], False) == "No matching rows in this time range."
    assert headline(["kind"], [["DHCP lease"]], False, None, None, NO_LEASE) == ("kind: DHCP lease")
    window = "for the last 24 hours"
    assert counted_line(["kind"], 0, 2, window, None, NO_LEASE) == (
        f"Read 2 sources for the last 24 hours. {NO_LEASE}"
    )
    assert counted_line(["kind"], 0, 2, window, None) == (
        "Read 2 sources for the last 24 hours: no rows."
    )
    assert counted_line(["kind"], 3, 2, window, None, NO_LEASE) == (
        "Read 2 sources for the last 24 hours."
    )


def test_rows_with_event_ids_have_it_once_as_the_headline() -> None:
    """Ask's results show no second copy (AskResults); the headline is the one place."""
    cols = ["event_id", "time"]
    assert headline(cols, [], False, None, None, NO_LEASE) == NO_LEASE
    assert counted_line(cols, 0, 2, "for today", None, NO_LEASE) is None
