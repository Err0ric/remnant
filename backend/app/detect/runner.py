"""Run an imported Sigma rule over a time range (ADR-0006 rows 2, 5, 6; Slice 4).

Scope is server-side (CLAUDE.md rule 13): the sources a run reads are the caller's
permitted sources that also have a template declaring a logsource the rule applies to.
A rule with no such source is recorded as `no_data` and reads nothing. The rule's stored
YAML is compiled again at run time, so the condition always comes from the pinned version,
and the query runs through the engine's guard, read-only connection, and timeout.

Each run stores the rule version it used, the sources it read, the total match count, and
up to `MAX_STORED_MATCHES` event ids (earliest first). Runs are audited as `rule.run`.

Who sees what: a run is listed to a caller only when every source it read is one the
caller may read now; matches are filtered by the caller's sources the same way.
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.auth.users import User
from app.core.errors import AppError, ForbiddenError, NotFoundError, ParamInvalidError
from app.core.ids import AUTO_PARSER, new_id
from app.detect.logsource import LogSource, applies
from app.detect.rules import compile_rule
from app.detect.store import RuleStore
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.ingest.sources import SourceStore
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.templates.registry import TemplateRegistry
from app.templates.router import routable
from app.templates.validator import Template

MAX_STORED_MATCHES = 1_000
MAX_RANGE = timedelta(days=366)
RUN_TIMEOUT_S = 60.0
AUTO_SEEN_WINDOW = timedelta(days=30)
AUTO_SEEN_TTL_S = 60.0


@dataclass(frozen=True, slots=True)
class RunRow:
    run_id: str
    rule_id: str
    sha256: str
    title: str  # of the version that ran (DRL 1.1: shown with every match)
    author: str
    level: str
    started_by: str
    started_at: str
    range_start: str
    range_end: str
    status: str
    match_count: int
    matches_stored: int
    elapsed_ms: int
    sources_in_scope: list[str]
    error: str | None


@dataclass(frozen=True, slots=True)
class MatchRow:
    event_id: str
    event_time: str | None
    source_id: str


class RuleRunner:
    def __init__(
        self,
        meta: MetaDB,
        engine: QueryEngine,
        sources: SourceStore,
        templates: TemplateRegistry,
        rules: RuleStore,
        audit: AuditLog,
    ) -> None:
        self._meta = meta
        self._engine = engine
        self._sources = sources
        self._templates = templates
        self._seen_cache: dict[tuple[str, ...], tuple[float, dict[str, set[str]]]] = {}
        self._rules = rules
        self._audit = audit

    def _declared(self) -> list[tuple[str, list[LogSource]]]:
        out: list[tuple[str, list[LogSource]]] = []
        for src in self._sources.list():
            if src.template_id == AUTO_PARSER:
                # Automatic sources (ADR-0012) hold rows from any routable template; run()
                # keeps a rule to the rows whose own template declares its logsource.
                auto = [ls for t in self._templates.all() if routable(t) for ls in _logsources(t)]
                out.append((src.source_id, auto))
                continue
            template = self._templates.get(src.template_id) if src.template_id else None
            if template is not None:
                out.append((src.source_id, _logsources(template)))
        return out

    def _auto_rows(self, logsource: LogSource, sources: list[str]) -> str:
        """Extra condition for Automatic sources in scope: only rows read by a template that
        declares this logsource. Empty when no Automatic source is in scope."""
        autos = {s.source_id for s in self._sources.list() if s.template_id == AUTO_PARSER}
        autos &= set(sources)
        if not autos:
            return ""
        ids = sorted(
            t.id
            for t in self._templates.all()
            if routable(t) and applies(logsource, _logsources(t))
        )
        # Source and template ids are [a-z0-9_] by validation, so quoting them is safe.
        auto_list = ", ".join(f"'{a}'" for a in sorted(autos))
        id_list = ", ".join(f"'{i}'" for i in ids) or "NULL"
        return f" AND (source_id NOT IN ({auto_list}) OR template_id IN ({id_list}))"

    def applicable_sources(self, logsource: LogSource) -> list[str]:
        """Configured sources whose template declares a logsource this rule applies to."""
        return [sid for sid, declared in self._declared() if applies(logsource, declared)]

    def sources_by_logsource(
        self, logsources: set[LogSource], user: User
    ) -> dict[LogSource, list[str]]:
        """For listing: the sources each logsource would read for this caller."""
        allowed = permitted_sources(self._meta, user)
        declared = self._declared()
        if allowed is not None:
            permitted = set(allowed)
            declared = [(sid, d) for sid, d in declared if sid in permitted]
        # An Automatic source could hold any routable template's rows, so _declared lists
        # them all (right for running). For listing, show only templates it has actually
        # used, or every Windows rule would name a Linux syslog source.
        seen = self._auto_seen([sid for sid, _ in declared if sid in self._auto_ids()])
        if seen is not None:
            declared = [
                (sid, self._seen_logsources(seen.get(sid, set())) if sid in seen else d)
                for sid, d in declared
            ]
        return {ls: [sid for sid, d in declared if applies(ls, d)] for ls in logsources}

    def _auto_ids(self) -> set[str]:
        return {s.source_id for s in self._sources.list() if s.template_id == AUTO_PARSER}

    def _seen_logsources(self, template_ids: set[str]) -> list[LogSource]:
        out: list[LogSource] = []
        for tid in sorted(template_ids):
            template = self._templates.get(tid)
            if template is not None:
                out.extend(_logsources(template))
        return out

    def _auto_seen(self, autos: list[str]) -> dict[str, set[str]] | None:
        """Templates each Automatic source used in the last 30 days, cached for a minute.
        None (list every routable template) when it cannot be read."""
        if not autos:
            return {}
        key = tuple(sorted(autos))
        now = time.monotonic()
        cached = self._seen_cache.get(key)
        if cached is not None and now - cached[0] < AUTO_SEEN_TTL_S:
            return cached[1]
        scope = QueryScope(sources=list(key), start=datetime.now(UTC) - AUTO_SEEN_WINDOW)
        try:
            result = self._engine.run(
                "SELECT DISTINCT source_id, template_id FROM events WHERE template_id IS NOT NULL",
                scope,
                timeout_s=10,
            )
        except AppError:
            return None
        seen: dict[str, set[str]] = {sid: set() for sid in key}
        for sid, tid in result.rows:
            seen.setdefault(str(sid), set()).add(str(tid))
        self._seen_cache[key] = (now, seen)
        return seen

    def run(
        self, rule_id: str, user: User, start: datetime, end: datetime, ip: str | None
    ) -> RunRow:
        if start.tzinfo is None or end.tzinfo is None:
            raise ParamInvalidError("Start and end need a time zone")
        if not start < end or end - start > MAX_RANGE:
            raise ParamInvalidError("End must be after start, at most 366 days apart")
        row, text = self._rules.get(rule_id)
        if not row.enabled and user.role != "admin":
            raise ForbiddenError("This rule is disabled; an administrator can enable it")
        run_id = new_id()
        started = datetime.now(UTC)
        detail: dict[str, object] = {
            "run_id": run_id,
            "rule_id": rule_id,
            "sha256": row.sha256,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        status, count, elapsed = "ok", 0, 0
        matches: list[MatchRow] = []
        read: list[str] = []
        error: str | None = None
        try:
            compiled = compile_rule(text.encode("utf-8"))
            allowed = permitted_sources(self._meta, user)
            candidates = self.applicable_sources(compiled.logsource)
            if allowed is not None:
                permitted = set(allowed)
                candidates = [s for s in candidates if s in permitted]
            scope = QueryScope(sources=candidates, start=start, end=end)
            where = f"({compiled.condition}){self._auto_rows(compiled.logsource, candidates)}"
            read = self._engine.sources_in(scope) if candidates else []
            if not read:
                status = "no_data"
            else:
                total = self._engine.run(
                    f"SELECT count(*) FROM events WHERE {where}",  # noqa: S608  # compiled, guard-checked condition
                    scope,
                    timeout_s=RUN_TIMEOUT_S,
                )
                count = int(total.rows[0][0]) if total.rows else 0
                if count:
                    columns = (
                        "CAST(event_id AS VARCHAR), CAST(coalesce(time, time_observed)"
                        " AS VARCHAR) AS t, source_id"
                    )
                    sql = f"SELECT {columns} FROM events WHERE {where} ORDER BY t, 1"  # noqa: S608  # as above
                    found = self._engine.run(
                        sql,
                        scope,
                        row_cap=MAX_STORED_MATCHES,
                        timeout_s=RUN_TIMEOUT_S,
                    )
                    matches = [MatchRow(str(r[0]), r[1], str(r[2])) for r in found.rows]
                    elapsed += found.elapsed_ms
                elapsed += total.elapsed_ms
        except AppError as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        self._save(
            run_id, row.rule_id, row.sha256, user, started, start, end,
            status, count, matches, elapsed, read, error,
        )  # fmt: skip
        detail |= {"status": status, "matches": count, "sources_in_scope": read}
        if error:
            detail["error"] = error
        self._audit.write("rule.run", "failure" if error else "success", user.user_id, ip, detail)
        return self.get_run(run_id, user)

    def _save(
        self,
        run_id: str,
        rule_id: str,
        sha256: str,
        user: User,
        started: datetime,
        start: datetime,
        end: datetime,
        status: str,
        count: int,
        matches: list[MatchRow],
        elapsed: int,
        read: list[str],
        error: str | None,
    ) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO rule_runs (run_id, rule_id, sha256, started_by, started_at,"
                " range_start, range_end, status, match_count, matches_stored, elapsed_ms,"
                " sources_in_scope, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    rule_id,
                    sha256,
                    user.user_id,
                    started.isoformat(),
                    start.astimezone(UTC).isoformat(),
                    end.astimezone(UTC).isoformat(),
                    status,
                    count,
                    len(matches),
                    elapsed,
                    json.dumps(read),
                    error,
                ),
            )
            con.executemany(
                "INSERT INTO rule_matches (run_id, event_id, event_time, source_id)"
                " VALUES (?, ?, ?, ?)",
                [(run_id, m.event_id, m.event_time, m.source_id) for m in matches],
            )

    # --- reading runs and matches -----------------------------------------------------------

    def _visible(self, user: User, read: list[str]) -> bool:
        allowed = permitted_sources(self._meta, user)
        return allowed is None or set(read) <= set(allowed)

    def runs(self, user: User, rule_id: str | None = None, limit: int = 50) -> list[RunRow]:
        sql = _RUN_SELECT + (" WHERE r.rule_id = ?" if rule_id else "")
        sql += " ORDER BY r.started_at DESC LIMIT ?"
        args: tuple[object, ...] = (rule_id, limit * 4) if rule_id else (limit * 4,)
        with self._meta.connect() as con:
            rows = [_run(r) for r in con.execute(sql, args).fetchall()]
        return [r for r in rows if self._visible(user, r.sources_in_scope)][:limit]

    def get_run(self, run_id: str, user: User) -> RunRow:
        with self._meta.connect() as con:
            r = con.execute(_RUN_SELECT + " WHERE r.run_id = ?", (run_id,)).fetchone()
        if r is None:
            raise NotFoundError("No such run")
        run = _run(r)
        if not self._visible(user, run.sources_in_scope):
            raise NotFoundError("No such run")
        return run

    def matches(self, run_id: str, user: User) -> list[MatchRow]:
        self.get_run(run_id, user)  # visibility check
        allowed = permitted_sources(self._meta, user)
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT event_id, event_time, source_id FROM rule_matches WHERE run_id = ?"
                " ORDER BY event_time, event_id",
                (run_id,),
            ).fetchall()
        return [
            MatchRow(r["event_id"], r["event_time"], r["source_id"])
            for r in rows
            if allowed is None or r["source_id"] in allowed
        ]


_RUN_SELECT = (
    "SELECT r.run_id, r.rule_id, r.sha256, v.title, v.author, v.level, r.started_by,"
    " r.started_at, r.range_start, r.range_end, r.status, r.match_count, r.matches_stored,"
    " r.elapsed_ms, r.sources_in_scope, r.error"
    " FROM rule_runs r JOIN rule_versions v ON v.sha256 = r.sha256"
)


def _run(r: sqlite3.Row) -> RunRow:
    read = json.loads(r["sources_in_scope"])
    return RunRow(
        run_id=r["run_id"],
        rule_id=r["rule_id"],
        sha256=r["sha256"],
        title=r["title"],
        author=r["author"],
        level=r["level"],
        started_by=r["started_by"],
        started_at=r["started_at"],
        range_start=r["range_start"],
        range_end=r["range_end"],
        status=r["status"],
        match_count=r["match_count"],
        matches_stored=r["matches_stored"],
        elapsed_ms=r["elapsed_ms"],
        sources_in_scope=[str(s) for s in read] if isinstance(read, list) else [],
        error=r["error"],
    )


def _logsources(template: Template) -> list[LogSource]:
    return [LogSource(e.product, e.service, e.category) for e in template.sigma.logsource]
