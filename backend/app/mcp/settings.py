"""The MCP server's installation settings: off by default (ADR-0003 rows 1 and 4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.meta.db import MetaDB


@dataclass(frozen=True, slots=True)
class McpSettings:
    enabled: bool = False
    # The clients and their models run on the internal network: local-only sources may
    # be returned. The server cannot see which model a client uses, so the default is cloud.
    endpoint_local: bool = False
    updated_at: str | None = None
    updated_by: str | None = None


class McpSettingsStore:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def get(self) -> McpSettings:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT enabled, endpoint_local, updated_at, updated_by FROM mcp_settings"
                " WHERE id = 1"
            ).fetchone()
        if row is None:
            return McpSettings()
        return McpSettings(bool(row[0]), bool(row[1]), row[2], row[3])

    def save(self, enabled: bool, endpoint_local: bool, user_id: str) -> McpSettings:
        now = datetime.now(UTC).isoformat()
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO mcp_settings (id, enabled, endpoint_local, updated_at, updated_by)"
                " VALUES (1, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET"
                " enabled = excluded.enabled, endpoint_local = excluded.endpoint_local,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (int(enabled), int(endpoint_local), now, user_id),
            )
        return McpSettings(enabled, endpoint_local, now, user_id)
