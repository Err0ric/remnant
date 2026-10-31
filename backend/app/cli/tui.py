"""`remnant tui`: query box, results table, and a tail pane, all through the server API.

Log content is untrusted: every value is shown as a plain rich Text (never parsed as
markup) after `clean()` strips terminal control sequences.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, Label, RichLog, Select, Static

from app.cli.banner import banner
from app.cli.client import Api, ApiError
from app.cli.output import clean
from app.cli.tailing import TailCursor
from app.core.branding import PRODUCT_NAME

_SQL = re.compile(r"\s*(select|with)\b", re.IGNORECASE)
CELL_CHARS = 200
TAIL_LINES = 50


def plain(value: Any, limit: int = CELL_CHARS) -> Text:
    """A value as inert text: control sequences removed, no markup, length capped."""
    text = clean(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return Text(text)


class Tui(App[None]):
    TITLE = PRODUCT_NAME
    CSS = """
    Screen { layout: vertical; }
    #banner { height: 4; margin: 0 1; padding: 0 1; }
    #query { margin: 0 1; }
    #status { height: 1; margin: 0 2; color: $text-muted; }
    #results { height: 1fr; margin: 0 1; }
    #tail-bar { height: 3; margin: 0 1; }
    #tail-bar Label { padding: 1 1 0 0; }
    #tail-source { width: 40; }
    #tail { height: 12; margin: 0 1; border: solid $panel; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+l", "focus_query", "Query"),
        Binding("ctrl+t", "toggle_tail", "Pause tail"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        api: Api,
        source: str | None = None,
        start: str | None = None,
        interval: float = 2.0,
    ) -> None:
        super().__init__()
        self.api = api
        self.start = start
        self.interval = interval
        self.tail_source = source
        self.tail_paused = False
        self._cursor: TailCursor | None = None
        self._gen = 0  # bumped to end the running stream (source change, pause, quit)

    def compose(self) -> ComposeResult:
        yield Static(self.banner_text(), id="banner")
        yield Input(
            placeholder="SQL, or a simple search like: sshd failed -user:root",
            id="query",
        )
        yield Label("Enter runs the query. Nothing runs until you press it.", id="status")
        yield DataTable(id="results", zebra_stripes=True, cursor_type="row")
        with Vertical():
            with Horizontal(id="tail-bar"):
                yield Label("Tail")
                yield Select[str]([], prompt="Pick a source to follow", id="tail-source")
            yield RichLog(id="tail", max_lines=2000, wrap=False, markup=False)
        yield Footer()

    def banner_text(self) -> Text:
        """The mark in the accent color and the product name in block letters."""
        text = Text(no_wrap=True, overflow="crop")
        for i, (mark, word) in enumerate(banner(PRODUCT_NAME)):
            if i:
                text.append("\n")
            text.append(mark, style="bold #7aaefa")  # --accent-text (DESIGN.md)
            text.append("  ")
            text.append(word, style="bold")
        text.append("\n")
        text.append(" " * (len(banner(PRODUCT_NAME)[0][0]) + 2))
        text.append("Security workspace · terminal", style="dim")
        return text

    def on_mount(self) -> None:
        self.query_one("#query", Input).focus()
        self.load_sources()

    # Query ------------------------------------------------------------------------------

    @on(Input.Submitted, "#query")
    def submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.set_status("Running...")
            self.run_query(text)

    @work(thread=True, exclusive=True, group="query")
    def run_query(self, text: str) -> None:
        try:
            if _SQL.match(text):
                data = self.api.query(text, start=self.start)
            else:
                compiled = self.api.compile_search(text)
                data = self.api.query(
                    compiled["sql"], start=self.start, params=compiled["params"] or None
                )
        except ApiError as exc:
            self.call_from_thread(self.set_status, f"Error: {clean(exc.detail)}")
            return
        self.call_from_thread(self.show_results, data)

    def show_results(self, data: dict[str, Any]) -> None:
        table = self.query_one("#results", DataTable)
        table.clear(columns=True)
        table.add_columns(*(plain(c, 60) for c in data["columns"]))
        for row in data["rows"]:
            table.add_row(*(plain(v) for v in row))
        note = " (truncated)" if data.get("truncated") else ""
        self.set_status(f"{len(data['rows'])} rows · {data['elapsed_ms']} ms{note}")

    def set_status(self, text: str) -> None:
        self.query_one("#status", Label).update(Text(text))

    # Tail -------------------------------------------------------------------------------

    @work(thread=True, group="sources")
    def load_sources(self) -> None:
        try:
            sources = self.api.sources()
        except ApiError as exc:
            self.call_from_thread(self.tail_note, f"Cannot list sources: {clean(exc.detail)}")
            return
        self.call_from_thread(self.fill_sources, sources)

    def fill_sources(self, sources: list[str]) -> None:
        select = self.query_one("#tail-source", Select)
        select.set_options((clean(s), s) for s in sources)
        if self.tail_source in sources:
            select.value = self.tail_source
        elif self.tail_source:
            self.tail_note(f"Source {clean(self.tail_source)} is not one you can read.")

    @on(Select.Changed, "#tail-source")
    def pick_source(self, event: Select.Changed) -> None:
        log = self.query_one("#tail", RichLog)
        log.clear()
        if not isinstance(event.value, str):
            self._cursor = None
            return
        self.tail_source = event.value
        self._gen += 1
        self._cursor = TailCursor(self.api, event.value, start=self.start)
        self.fetch_tail(first=True)

    @work(thread=True, group="tail")
    def fetch_tail(self, first: bool) -> None:
        """The latest lines, then the server's live stream (ADR-0036 row 10): the same
        limits and audit as Live on Search. Pause ends the stream; Resume starts a new one
        from the last line shown."""
        cursor = self._cursor
        if cursor is None:
            return
        gen = self._gen
        try:
            if first:
                data = cursor.latest(TAIL_LINES)
                if data["rows"]:
                    self.call_from_thread(self.write_tail, data["rows"])
            since, after = cursor.cursor()
            for event, body in self.api.live(
                cursor.follow_sql(), "tui", since, after,
                stop=lambda: gen != self._gen or self.tail_paused,
            ):  # fmt: skip
                if event == "rows" and body["rows"]:
                    cursor.advance(body["cursor"])
                    self.call_from_thread(self.write_tail, body["rows"])
                elif event in ("notice", "end"):
                    self.call_from_thread(self.tail_note, clean(str(body.get("message", ""))))
        except ApiError as exc:
            self.call_from_thread(self.tail_note, f"Tail stopped: {clean(exc.detail)}")

    def write_tail(self, rows: list[list[Any]]) -> None:
        log = self.query_one("#tail", RichLog)
        for row in rows:
            log.write(Text("  ").join(plain(v, 400) for v in row))

    def tail_note(self, text: str) -> None:
        self.query_one("#tail", RichLog).write(Text(text, style="italic"))

    # Actions ----------------------------------------------------------------------------

    def action_focus_query(self) -> None:
        self.query_one("#query", Input).focus()

    def action_toggle_tail(self) -> None:
        self.tail_paused = not self.tail_paused
        self.tail_note("Tail paused." if self.tail_paused else "Tail resumed.")
        if not self.tail_paused and self._cursor is not None:
            self._gen += 1
            self.fetch_tail(first=False)
