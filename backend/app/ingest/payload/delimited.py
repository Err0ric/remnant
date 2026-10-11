"""Positional CSV payloads (Palo Alto, Snare): column names come from the template.

Columns named "" or "_" are skipped (vendor "future use" slots). Empty cells become None.
Extra cells go to `_extra` (partial unless trailing="ignore"); fewer cells than columns
mark the result partial.
"""

import csv

from app.ingest.payload.base import PayloadResult


class CsvParser:
    def __init__(
        self,
        columns: list[str],
        delimiter: str = ",",
        quote: str = '"',
        trailing: str = "partial",
    ) -> None:
        if not columns:
            raise ValueError("csv needs at least one column name")
        if len(delimiter) != 1 or len(quote) != 1 or delimiter == quote:
            raise ValueError("csv delimiter and quote must be distinct single characters")
        self._columns = columns
        self._delimiter = delimiter
        self._quote = quote
        # "ignore": vendors append columns in new releases; extra cells are kept in
        # _extra without marking the row partial.
        self._trailing_ok = trailing == "ignore"

    def parse(self, text: str) -> PayloadResult:
        try:
            cells = next(csv.reader([text], delimiter=self._delimiter, quotechar=self._quote))
        except (csv.Error, StopIteration) as exc:
            return PayloadResult(error=f"csv: {exc}"[:200])
        fields: dict[str, object] = {}
        for name, cell in zip(self._columns, cells, strict=False):
            if name and name != "_":
                fields[name] = cell if cell != "" else None
        partial = len(cells) < len(self._columns) or (
            len(cells) > len(self._columns) and not self._trailing_ok
        )
        if len(cells) > len(self._columns):
            fields["_extra"] = cells[len(self._columns) :]
        return PayloadResult(fields, partial=partial)
