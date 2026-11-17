"""A library query whose SQL the server builds (fix list 2026-11-16 item 20): checked with
the shipped AI catalog at load, built from the live catalog when it is asked."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.catalog import Service
from app.core.errors import ConfigError, QueryBlockedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.library import BUILTINS, LIBRARY_DIR, Library, LibraryQuery, load, load_dir

BASE = {"id": "q", "name": "Q", "group": "G", "why": "w", "normal": "n"}


def mine() -> list[Service]:
    return [
        Service("chat_internal", "Our 'own' chat", "", "chat", ("chat.example.com",),
                "approved", True, ""),
        Service("ads", "Ad tags", "", "non_usage", ("ads.example.com",), "unreviewed", True, ""),
    ]  # fmt: skip


def test_a_query_needs_sql_or_a_builtin() -> None:
    with pytest.raises(ValidationError):
        LibraryQuery.model_validate(BASE)
    assert LibraryQuery.model_validate({**BASE, "builtin": "ai_services"}).sql == ""


def test_the_builtin_is_built_from_the_live_catalog() -> None:
    lib = Library(load_dir(LIBRARY_DIR), mine)
    found = lib.find("ai_services", "ai_services_in_use")
    assert found is not None
    shipped = found[1]
    assert "claude.ai" in shipped.sql  # loaded with the shipped catalog
    live = lib.resolve(shipped).sql
    assert "chat.example.com" in live and "claude.ai" not in live
    # A name is a quoted literal; a non-usage service is matched but never listed.
    assert "'Our ''own'' chat'" in live and "Ad tags" not in live
    assert lib.resolve(lib.packs[0].queries[0]) is lib.packs[0].queries[0]


PACK = """schema_version: 1
id: {id}
name: Mine
version: 1.0.0
queries:
- id: q
  name: Q
  group: G
  why: w
  normal: n
  {body}
"""


def test_builtin_only_in_packs_shipped_with_the_product(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D266: a pack in any other folder that names a builtin is refused at load, logged,
    and the rest still load; the shipped pack keeps its builtin."""
    for pid, body in (("mine", "builtin: ai_services"), ("plain", "sql: SELECT 1 AS n")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "pack.yaml").write_text(PACK.format(id=pid, body=body))
    with pytest.raises(ConfigError, match="only packs shipped with the product"):
        load(tmp_path / "mine" / "pack.yaml")
    assert [p.id for p in load_dir(tmp_path)] == ["plain"]
    shipped_ids = [p.id for p in load_dir(LIBRARY_DIR)]
    assert "ai_services" in shipped_ids


def test_a_builtin_still_goes_through_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server-built SQL is not trusted for being server-built: a builtin that returned
    anything but one SELECT is refused at load and when it runs."""
    monkeypatch.setitem(BUILTINS, "ai_services", lambda _s: "DELETE FROM events")
    with pytest.raises(ConfigError):
        load(LIBRARY_DIR / "ai_services" / "pack.yaml", True)
    lib = Library(load_dir(tmp_path), mine)
    q = LibraryQuery.model_validate({**BASE, "builtin": "ai_services"})
    with pytest.raises(QueryBlockedError):
        QueryEngine(tmp_path).run(lib.resolve(q).sql, QueryScope(None))
