"""A Simple search term without a wildcard is found with `contains` instead of `ILIKE`
(owner item P6, 2026-11-17: an address searched over 30 days took 21 to 27 s). These
tests hold it to the old meaning: the same rows, in the same order, as the `ILIKE
'%text%' ESCAPE '\\'` it replaces, on strings built to break it (Unicode case pairs,
characters whose lower case is ASCII, LIKE's own wildcards and escape, NULLs), on random
strings with a fixed seed, and through the engine on a synthetic lake (first page and
field counts)."""

# ruff: noqa: RUF001  # look-alike letters are the point of these strings

import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
import pytest

from app.api.query import text_facet_sql
from app.core.schema import COLUMN_NAMES
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import rows_table
from app.search.newest import keyed_sql, newest_first
from app.search.simple import compile_search

TRICKY = [
    "İstanbul", "istanbul", "ISTANBUL", "ıi", "Kelvin K 5 K", "k", "Straße", "STRASSE",
    "ǅungla", "ǆ", "ΣΑΣ σας ς", "ﬃ office", "é", "é", "Ω Ω", "ﬀ", "ǰ",
    "100% done", "a_b", "a\\b", "50%_off", "", " ", "\t", "🙂 ok", "Ⅻ ⅻ", "Ａｂｃ ａｂｃ",
    "Failed password for root from 192.0.2.15 port 22", "192.0.2.150", "192.0.2.1",
    "2001:DB8::1", "2001:db8::1", "12:30:01", "-1.5e3", "a.b", "A.B",
]  # fmt: skip
TERMS = [
    *TRICKY,
    "i", "I", "İ", "ı", "K", "K", "ss", "SS", "ß", "σ", "Σ", "ς", "ffi", "%", "_", "\\",
    "192.0.2.15", "192.0.2.1", "2001:db8", "DB8", "e", "́", "ok", "abc", "ⅻ", "Ⅻ",
]  # fmt: skip


def legacy(sql: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The SQL the compiler wrote before this change: `ILIKE '%text%' ESCAPE '\\'`."""
    out = dict(params)

    def back(m: re.Match[str]) -> str:
        col, p = m.group("col"), m.group("p")
        return f"{col} ILIKE ${p} ESCAPE '\\'"

    new = re.sub(r"contains\(lower\((?P<col>raw|message)\), lower\(\$(?P<p>p\d+)\)\)", back, sql)
    new = re.sub(r"contains\((?P<col>raw|message), \$(?P<p>p\d+)\)", back, new)
    for name in set(re.findall(r"\$(p\d+) ESCAPE", new)) - set(re.findall(r"\$(p\d+) ESCAPE", sql)):
        v = str(params[name])
        out[name] = "%" + v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return new, out


def test_the_legacy_form_is_what_the_compiler_wrote() -> None:
    new = compile_search("sshd 192.0.2.15")
    old, params = legacy(new.sql, new.params)
    assert "raw ILIKE $p0 ESCAPE '\\' OR message ILIKE $p0 ESCAPE '\\'" in old
    assert "raw ILIKE $p1 ESCAPE '\\' OR message ILIKE $p1 ESCAPE '\\'" in old
    assert params == {"p0": "%sshd%", "p1": "%192.0.2.15%"}
    assert "contains(raw, $p1)" in new.sql and "contains(lower(raw), lower($p0))" in new.sql
    wild = compile_search("ssh*d")
    assert "ILIKE $p0 ESCAPE" in wild.sql and wild.params == {"p0": "%ssh%d%"}


@pytest.fixture(scope="module")
def table() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    rng = random.Random(17)
    alphabet = "".join(TRICKY) + "abcXYZ019.:%_\\ "
    rows: list[tuple[str, str | None, str | None]] = []
    for i, s in enumerate(TRICKY):
        rows.append((f"t{i:03d}", s, None))
        rows.append((f"u{i:03d}", None, s.upper()))
        rows.append((f"v{i:03d}", s.lower(), s.swapcase()))
    for i in range(400):

        def one() -> str:
            return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 24)))

        rows.append((f"r{i:03d}", one(), one() if i % 3 else None))
    rows.append(("n000", None, None))
    con.execute("CREATE TABLE events (event_id VARCHAR, raw VARCHAR, message VARCHAR)")
    con.executemany("INSERT INTO events VALUES (?, ?, ?)", rows)
    return con


def ids(con: duckdb.DuckDBPyConnection, sql: str, params: dict[str, Any]) -> list[str]:
    return [r[0] for r in con.execute(sql + "\nORDER BY event_id", params or None).fetchall()]


def searches() -> list[str]:
    rng = random.Random(5)
    out = []
    for t in TERMS:
        q = t.replace("\\", "\\\\").replace('"', '\\"')
        out += [f'"{q}"', f'-"{q}"', f'"{q}" OR "{q.swapcase()}"', f'"{q.upper()}" "{q.lower()}"']
    for _ in range(300):  # random pieces of the strings, case flipped at random
        s = rng.choice(TRICKY) or "x"
        a = rng.randrange(len(s))
        piece = "".join(
            c.swapcase() if rng.random() < 0.5 else c for c in s[a : a + rng.randrange(1, 5)]
        )
        out.append('"' + piece.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return out


@pytest.mark.parametrize("text", searches())
def test_contains_finds_what_ilike_found(table: duckdb.DuckDBPyConnection, text: str) -> None:
    new = compile_search(text, select="event_id", ordered=False)
    assert "ILIKE" not in new.sql
    old_sql, old_params = legacy(new.sql, new.params)
    assert ids(table, new.sql, new.params) == ids(table, old_sql, old_params)


def test_the_cases_match_something(table: duckdb.DuckDBPyConnection) -> None:
    """The tricky rows are matched both ways, so the comparison above is not vacuous."""
    for text, least in (('"istanbul"', 3), ('"k"', 5), ('"192.0.2.15"', 2), ('"%"', 4)):
        c = compile_search(text, select="event_id", ordered=False)
        assert len(ids(table, c.sql, c.params)) >= least


# --- through the engine, on a synthetic lake ---------------------------------------------

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def row(source: str, at: datetime, i: int, rng: random.Random) -> dict[str, Any]:
    ip = f"192.0.2.{rng.randrange(1, 40)}"
    peer = f"198.51.100.{rng.randrange(1, 20)}"
    words = rng.choice(["Failed password", "Accepted publickey", "İstanbul login", "STRASSE"])
    r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    r.update(
        event_id=str(uuid.UUID(int=rng.getrandbits(128))), source_id=source, template_id="t",
        template_version="1", time=None if i % 9 == 0 else at, time_observed=at,
        raw=f"<13>{at:%b %d %H:%M:%S} gw sshd[{i}]: {words} for alice from {ip} to {peer}",
        raw_bytes_invalid=False, parse_status="ok" if i % 4 else "partial",
        classification="internal", owner_id="system",
        message=None if i % 5 == 0 else f"{words} {ip if i % 3 else ''}",
        # Some lines hold the address in the text only, never in a column.
        src_endpoint_ip=ip if i % 4 else None, dst_endpoint_ip=peer,
        actor_user_name="alice" if i % 2 else "bob", device_hostname="gw.example.internal",
    )  # fmt: skip
    return r


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root: Path = tmp_path_factory.mktemp("textmatch") / "lake"
    rng = random.Random(11)
    for d in range(12):
        for source in ("fw", "dns"):
            rows = [row(source, NOW - timedelta(days=d, minutes=rng.randrange(1440)), i, rng)
                    for i in range(60)]  # fmt: skip
            folder = root / f"source={source}" / f"day={(NOW - timedelta(days=d)).date()}"
            folder.mkdir(parents=True)
            pq.write_table(rows_table(rows), folder / "part-0.parquet")
    return root


ENGINE_TEXTS = [
    "192.0.2.15", '"192.0.2.1"', "192.0.2.1 OR 198.51.100.7", "-192.0.2.15", "failed",
    "FAILED 192.0.2.3", "istanbul", "strasse", "user:alice 192.0.2.5", "src_ip:192.0.2.5",
    "src_ip:192.0.2.* -198.51.100.1", "parse_status:partial 198.51.100", "fail* 192.0.2",
    "(accepted OR failed) -user:bob", "",
]  # fmt: skip
SCOPES = [QueryScope(None, NOW - timedelta(days=30)), QueryScope(["fw"], NOW - timedelta(days=3))]


@pytest.mark.parametrize("limit", [1, 25, 1000])
@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", ENGINE_TEXTS)
def test_the_first_page_is_the_same_rows_in_the_same_order(
    lake: Path, text: str, scope: QueryScope, limit: int
) -> None:
    engine = QueryEngine(lake, default_limit=limit)
    got = newest_first(engine, text, scope)
    sql, params = keyed_sql(text, limit + 1)
    old_sql, old_params = legacy(sql, params)
    want = engine.run(old_sql, scope, old_params or None).rows
    assert got.rows == [r[:-1] for r in want[:limit]]
    assert got.truncated == (len(want) > limit)


@pytest.mark.parametrize("text", ENGINE_TEXTS)
def test_field_counts_are_the_same(lake: Path, text: str) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql(text)
    old_sql, old_params = legacy(sql, params)
    assert (
        engine.run(sql, SCOPES[0], params or None).rows
        == engine.run(old_sql, SCOPES[0], old_params or None).rows
    )
