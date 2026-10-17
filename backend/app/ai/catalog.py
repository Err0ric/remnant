"""AI service catalog and review status (ADR-0015 rows 1 and 7).

The shipped catalog (`content/ai/services.yaml`) plus services an admin added, each
Approved, Not approved, or Unreviewed (no row). MCP servers are reviewed by name rules:
an exact name or a `prefix*`. Every change is audited by the caller.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import NotFoundError, ParamInvalidError
from app.meta.db import MetaDB

CATALOG_FILE = Path(__file__).resolve().parents[1] / "content" / "ai" / "services.yaml"
Kind = Literal[
    "chat", "api", "coding", "agent_platform", "mcp_registry", "image", "meetings", "writing"
]
Status = Literal["approved", "not_approved", "unreviewed"]
DataLevel = Literal["public", "internal", "confidential"]
DOMAIN = re.compile(r"^(?=.{3,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MCP_PATTERN = re.compile(r"^[A-Za-z0-9_.@/:-]{1,120}\*?$")


class ServiceDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=80)
    vendor: str = Field(default="", max_length=80)
    kind: Kind
    domains: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("domains")
    @classmethod
    def _domains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        out = tuple(d.strip().lower().rstrip(".") for d in value)
        for d in out:
            if not DOMAIN.fullmatch(d):
                raise ValueError(f"{d[:80]!r} is not a domain name")
        return out


@dataclass(frozen=True, slots=True)
class Service:
    id: str
    name: str
    vendor: str
    kind: str
    domains: tuple[str, ...]
    status: Status
    custom: bool
    note: str
    # The most sensitive data allowed to this service (ADR-0020 row 4); None if not set.
    data_level: DataLevel | None = None


@dataclass(frozen=True, slots=True)
class McpRule:
    pattern: str
    status: Literal["approved", "not_approved"]
    note: str
    updated_at: str
    updated_by: str | None

    def matches(self, name: str) -> bool:
        if self.pattern.endswith("*"):
            return name.lower().startswith(self.pattern[:-1].lower())
        return name.lower() == self.pattern.lower()


@cache
def shipped() -> tuple[ServiceDef, ...]:
    data = yaml.safe_load(CATALOG_FILE.read_text(encoding="utf-8")) or []
    items = tuple(ServiceDef.model_validate(x) for x in data)
    ids = [s.id for s in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Catalog ids must be unique")
    return items


class Catalog:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def services(self) -> list[Service]:
        with self._meta.connect() as con:
            status = {r["service_id"]: r for r in con.execute("SELECT * FROM ai_service_status")}
            levels = {
                r["service_id"]: r["data_level"]
                for r in con.execute("SELECT * FROM ai_service_labels")
            }
            custom = con.execute("SELECT * FROM ai_custom_services ORDER BY name").fetchall()
        defs = [(d, False) for d in shipped()]
        for r in custom:
            defs.append(
                (
                    ServiceDef(
                        id=r["service_id"],
                        name=r["name"],
                        vendor=r["vendor"],
                        kind=r["kind"],
                        domains=tuple(json.loads(r["domains"])),
                    ),
                    True,
                )
            )
        out = []
        for d, is_custom in defs:
            row = status.get(d.id)
            out.append(
                Service(
                    d.id,
                    d.name,
                    d.vendor,
                    d.kind,
                    d.domains,
                    row["status"] if row else "unreviewed",
                    is_custom,
                    row["note"] if row else "",
                    levels.get(d.id),
                )
            )
        return out

    def domain_table(self) -> list[tuple[str, str]]:
        """(service id, domain) pairs for matching; every domain passed DOMAIN."""
        return [(s.id, d) for s in self.services() for d in s.domains]

    def set_status(self, service_id: str, status: Status, note: str, actor: str) -> Status:
        """Returns the previous status."""
        known = {s.id: s for s in self.services()}
        if service_id not in known:
            raise NotFoundError("No such AI service")
        before = known[service_id].status
        with self._meta.connect() as con:
            if status == "unreviewed":
                con.execute("DELETE FROM ai_service_status WHERE service_id = ?", (service_id,))
            else:
                con.execute(
                    "INSERT INTO ai_service_status (service_id, status, note, updated_at,"
                    " updated_by) VALUES (?, ?, ?, ?, ?) ON CONFLICT (service_id) DO UPDATE"
                    " SET status = excluded.status, note = excluded.note,"
                    " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                    (service_id, status, note[:500], _now(), actor),
                )
        return before

    def set_data_level(self, service_id: str, level: DataLevel | None, actor: str) -> str | None:
        """Returns the previous level."""
        known = {s.id: s for s in self.services()}
        if service_id not in known:
            raise NotFoundError("No such AI service")
        before = known[service_id].data_level
        with self._meta.connect() as con:
            if level is None:
                con.execute("DELETE FROM ai_service_labels WHERE service_id = ?", (service_id,))
            else:
                con.execute(
                    "INSERT INTO ai_service_labels (service_id, data_level, updated_at, updated_by)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (service_id) DO UPDATE"
                    " SET data_level = excluded.data_level, updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (service_id, level, _now(), actor),
                )
        return before

    def add_custom(self, d: ServiceDef, actor: str) -> None:
        if d.id in {s.id for s in self.services()}:
            raise ParamInvalidError("A service with this id already exists")
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO ai_custom_services (service_id, name, vendor, kind, domains,"
                " created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (d.id, d.name, d.vendor, d.kind, json.dumps(list(d.domains)), _now(), actor),
            )

    def delete_custom(self, service_id: str) -> None:
        with self._meta.connect() as con:
            n = con.execute(
                "DELETE FROM ai_custom_services WHERE service_id = ?", (service_id,)
            ).rowcount
            con.execute("DELETE FROM ai_service_status WHERE service_id = ?", (service_id,))
            con.execute("DELETE FROM ai_service_labels WHERE service_id = ?", (service_id,))
        if not n:
            raise NotFoundError("Only services added here can be removed")

    # --- MCP rules -----------------------------------------------------------------------

    def mcp_rules(self) -> list[McpRule]:
        with self._meta.connect() as con:
            rows = con.execute("SELECT * FROM ai_mcp_rules ORDER BY pattern").fetchall()
        return [
            McpRule(r["pattern"], r["status"], r["note"], r["updated_at"], r["updated_by"])
            for r in rows
        ]

    def set_mcp_rule(
        self,
        pattern: str,
        status: Literal["approved", "not_approved"] | None,
        note: str,
        actor: str,
    ) -> None:
        if not MCP_PATTERN.fullmatch(pattern):
            raise ParamInvalidError("An MCP rule is a server name, or a prefix ending in *")
        with self._meta.connect() as con:
            if status is None:
                con.execute("DELETE FROM ai_mcp_rules WHERE pattern = ?", (pattern,))
            else:
                con.execute(
                    "INSERT INTO ai_mcp_rules (pattern, status, note, updated_at, updated_by)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT (pattern) DO UPDATE SET"
                    " status = excluded.status, note = excluded.note,"
                    " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                    (pattern, status, note[:500], _now(), actor),
                )

    def mcp_status(self, name: str, rules: list[McpRule] | None = None) -> Status:
        """Exact rules win over prefixes; the longest prefix wins among prefixes."""
        rules = self.mcp_rules() if rules is None else rules
        exact = [r for r in rules if not r.pattern.endswith("*") and r.matches(name)]
        if exact:
            return exact[0].status
        prefixes = sorted(
            (r for r in rules if r.pattern.endswith("*") and r.matches(name)),
            key=lambda r: len(r.pattern),
            reverse=True,
        )
        return prefixes[0].status if prefixes else "unreviewed"


def _now() -> str:
    return datetime.now(UTC).isoformat()
