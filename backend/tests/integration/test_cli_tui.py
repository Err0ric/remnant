"""`remnant tui` against a real in-process server: query, tail, and inert log text."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rich.text import Text
from textual.widgets import DataTable, Input, Label, RichLog, Select

from app.cli.client import Api, Credentials
from app.cli.tui import Tui, plain
from app.core.config import load_config
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter
from app.main import create_app

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
LOG = (
    b"<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for jordan\n"
    b"<38>Oct  9 21:00:00 bastion sshd[2]: Failed password for admin\n"
    b"<38>Oct  9 21:05:00 bastion sshd[3]: [bold red]not markup[/] \x1b[31mred\x1b[0m\n"
)


def _write(lake: Path, data: bytes) -> None:
    n = Normalizer(SourceSpec(source_id="linux_auth", format="syslog"), clock=lambda: NOW)
    LakeWriter(lake).write(
        [r for f in Framer().frames([data]) if (r := n.normalize(decode_frame(f)))]
    )


@pytest.fixture
def api(tmp_path: Path) -> Api:
    _write(tmp_path / "lake", LOG)
    app = create_app(load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path)}))
    app.state.live.poll_s, app.state.live.limit_override_s = 0.05, 1.5

    def factory(creds: Credentials) -> TestClient:
        client = TestClient(app, base_url="http://127.0.0.1:8080")
        client.headers["Accept"] = "application/json"
        return client

    return Api(Credentials("http://127.0.0.1:8080", None), factory)


def _cells(table: DataTable[Text]) -> list[list[str]]:
    return [[c.plain for c in table.get_row_at(i)] for i in range(table.row_count)]


def test_runs_sql_and_simple_search_only_on_enter(api: Api) -> None:
    async def go() -> None:
        app = Tui(api)
        async with app.run_test(size=(140, 40)) as pilot:
            table = app.query_one("#results", DataTable)
            await pilot.press(*"SELECT actor_process_pid AS pid, message FROM events ORDER BY pid")
            await pilot.pause()
            assert table.row_count == 0  # typing alone runs nothing
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            rows = _cells(table)
            assert [r[0] for r in rows] == ["1", "2", "3"]
            # Log text is shown literally: no markup styling, no escape sequences.
            assert rows[2][1].startswith("[bold red]not markup[/] red")
            assert "3 rows" in str(app.query_one("#status", Label).render())

            box = app.query_one("#query", Input)
            box.value = '"failed password"'
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert table.row_count == 1

            box.value = "SELECT * FROM nowhere"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Error:" in str(app.query_one("#status", Label).render())

    asyncio.run(go())


def test_tail_follows_the_chosen_source(api: Api, tmp_path: Path) -> None:
    """The latest lines, then the live stream (ADR-0036 row 10): a line that arrives is
    added once, and the stream's end is noted in the pane."""

    async def go() -> None:
        app = Tui(api)
        async with app.run_test(size=(140, 40)) as pilot:
            await app.workers.wait_for_complete()
            select = app.query_one("#tail-source", Select)
            select.set_options([("linux_auth", "linux_auth")])
            select.value = "linux_auth"
            await pilot.pause(0.3)
            _write(tmp_path / "lake", b"<38>Oct  9 21:10:00 bastion sshd[4]: Connection closed\n")
            await app.workers.wait_for_complete()  # the stream ends at its time limit
            await pilot.pause()
            texts = [line.text for line in app.query_one("#tail", RichLog).lines]
            assert "Accepted publickey" in texts[0] and "not markup" in texts[2]
            assert sum("Connection closed" in t for t in texts) == 1
            assert "Live stopped after" in texts[-1]

    asyncio.run(go())


def test_plain_caps_and_strips() -> None:
    assert plain("x" * 500).plain == "x" * 199 + "…"
    assert plain("\x1b]0;title\x07ok").plain == "ok"


def test_banner_draws_the_product_name() -> None:
    from app.cli.banner import MARK, wordmark
    from app.core.branding import PRODUCT_NAME

    rows = wordmark(PRODUCT_NAME)
    assert len({len(r) for r in rows}) == 1  # equal width, so the block lines up
    assert len(MARK) == len(rows) == 3
    assert wordmark("ab") == ("┌─┐ ┌┐ ", "├─┤ ├┴┐", "┴ ┴ └─┘")
    assert wordmark("a?")[1] == "├─┤ ?"


def test_banner_shown_in_the_tui(api: Api) -> None:
    async def go() -> None:
        app = Tui(api)
        async with app.run_test(size=(140, 40)):
            from textual.widgets import Static

            text = app.query_one("#banner", Static).render()
            assert "Security workspace" in str(text)

    asyncio.run(go())
