"""One person's AI activity (owner, 2026-11-03; D189): what they use AI for, on one page.

Accounts (the Claude accounts the hooks plugin reported, by tier), devices, the AI services
the network saw for them, their Claude Code sessions newest first with a one-line summary,
rollups for the range (tools, files written or edited, commands by first word, web domains,
MCP servers), and flags (a personal account, blocked or failed tool calls, writes outside a
session's working folder, shell commands, an MCP server new in the range).

Metadata only, as the hooks plugin sends it: tool names, paths, hosts, program names, and
sizes. Never prompt or tool content. Deterministic SQL over the caller's own view; the
person is matched under every form of the name (`_mine`, the person timeline's condition).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.accounts import Account
from app.ai.internal_tools import INTERNAL_TOOLS
from app.ai.sessions import _ONE_COPY, _a
from app.ai.usage import _use_ctes, fact_range
from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import drill
from app.search.identity import IdentityMap, key_sql
from app.search.timeline import _mine

TIMEOUT_S = 20.0
MAX_ROWS = 20_000  # hook records for one person in the range; the rollups say when cut
TOP = 25  # rows per rollup
WRITE_TOOLS = frozenset({"write", "edit", "multiedit", "notebookedit"})
SHELL_TOOLS = frozenset({"bash", "powershell"})


@dataclass(slots=True)
class Count:
    name: str
    n: int


@dataclass(slots=True)
class ServiceSeen:
    service_id: str
    name: str
    events: int
    last_seen: str | None


@dataclass(slots=True)
class SessionLine:
    session_id: str
    machine: str | None
    started: str
    last: str
    summary: str
    flagged: bool


@dataclass(slots=True)
class Flag:
    kind: str  # personal_account | failed_calls | outside_folder | shell | new_mcp
    text: str
    count: int
    examples: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PersonAi:
    person: str
    start: str
    end: str
    accounts: list[Account] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    services: list[ServiceSeen] = field(default_factory=list)
    sessions: list[SessionLine] = field(default_factory=list)
    tools: list[Count] = field(default_factory=list)
    files: list[Count] = field(default_factory=list)  # written or edited, by path
    commands: list[Count] = field(default_factory=list)  # by first word
    domains: list[Count] = field(default_factory=list)
    mcp: list[Count] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    cut: bool = False  # more hook records than MAX_ROWS: rollups count the first ones
    sources: list[str] = field(default_factory=list)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.astimezone(UTC).isoformat() if isinstance(v, datetime) else str(v)


def _norm(path: str) -> str:
    """A path to compare by folder: forward slashes, no trailing slash, case kept except on
    Windows drive paths, which compare without case."""
    p = path.replace("\\", "/").rstrip("/")
    return p.lower() if len(p) > 1 and p[1] == ":" else p


def outside(path: str | None, cwd: str | None) -> bool:
    """True when a written path is not under the session's working folder. A relative path
    is under it; no folder reported means nothing is assumed."""
    if not path or not cwd:
        return False
    p, c = _norm(path), _norm(cwd)
    absolute = p.startswith("/") or (len(p) > 1 and p[1] == ":")
    if not absolute:
        return False
    return not (p == c or p.startswith(c + "/"))


def first_word(program: str | None) -> str | None:
    if not program:
        return None
    word = program.strip().split()[0] if program.strip() else ""
    return word.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:64] or None


def _counts(c: Counter[str]) -> list[Count]:
    return [Count(k, n) for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]]


def hooks_sql(mine: str) -> str:
    return f"""
WITH {_ONE_COPY}
SELECT {_a("session_id")}, coalesce(time, time_observed) AS t, message,
       {_a("tool_name")}, {_a("mcp_server_name")}, {_a("path")}, {_a("cwd")},
       {_a("program")}, {_a("web_host")}, device_hostname
FROM hooks
WHERE {mine}
ORDER BY t
LIMIT {MAX_ROWS + 1}"""  # noqa: S608  # the person condition is escaped literals only


MCP_FIRST_SQL = f"""
WITH {_ONE_COPY}
SELECT {_a("mcp_server_name")}, min(coalesce(time, time_observed))
FROM hooks WHERE {_a("mcp_server_name")} IS NOT NULL
GROUP BY 1"""  # noqa: S608  # fixed SQL text


def activity(
    engine: QueryEngine,
    allowed: list[str] | None,
    ident: IdentityMap,
    catalog_pairs: list[tuple[str, str]],
    service_names: dict[str, str],
    accounts: list[Account],
    person: str,
    now: datetime,
    days: int,
    rollup: Any = None,
) -> PersonAi:
    if not person.strip():
        raise ParamInvalidError("Give a person")
    keys = ident.keys_for(person)
    mine = _mine(ident, keys)
    end = now.astimezone(UTC)
    start = end - timedelta(days=days)
    scope = QueryScope(allowed, start, end)
    out = PersonAi(person=ident.key(person), start=start.isoformat(), end=end.isoformat())
    sources: set[str] = set()
    key_set = set(keys)

    # Accounts the plugin reported for this person (any form of the name).
    out.accounts = [a for a in accounts if a.email and ident.key(a.email) in key_set]

    # AI services the network saw for them: the same use rows as AI usage.
    org = "[" + ", ".join(drill.lit(d) for d in (ident.domains or [""])) + "]"
    key_who = key_sql("who").replace("$id_org", org)
    skip, covered, after = rollup.plan(scope) if rollup is not None else ([], [], None)
    res = engine.run(
        f"WITH {_use_ctes(catalog_pairs, bool(covered))}\n"  # catalog values checked upstream
        "SELECT service_id, sum(n), max(last_t),"
        " list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL)"
        f" FROM r WHERE list_contains({drill.lits(keys)}, {key_who})"
        " GROUP BY 1 ORDER BY 3 DESC LIMIT 100",
        scope,
        {"covered": covered, **fact_range(scope, end)} if covered else None,
        timeout_s=TIMEOUT_S, intel=False, rollup=bool(covered), skip_days=skip or (),
        name="person_ai.services", after=after, page=True,
    )  # fmt: skip
    sources.update(res.sources)
    devices: set[str] = set()
    for sid, n, last, devs in res.rows:
        out.services.append(
            ServiceSeen(str(sid), service_names.get(str(sid), str(sid)), int(n or 0), _iso(last))
        )
        devices.update(str(d) for d in devs or [])

    # Their Claude Code records from the hooks plugin.
    hooks = engine.run(
        hooks_sql(mine), scope, timeout_s=TIMEOUT_S, name="person_ai.hooks", page=True
    )
    sources.update(hooks.sources)
    rows = hooks.rows[:MAX_ROWS]
    out.cut = len(hooks.rows) > MAX_ROWS
    # First use of each MCP server by anyone, from 30 days before the range: one first
    # used inside the range is new.
    earlier = QueryScope(allowed, start - timedelta(days=30), end)
    firsts = {
        str(m): _iso(t) or ""
        for m, t in engine.run(
            MCP_FIRST_SQL, earlier, timeout_s=TIMEOUT_S, name="person_ai.mcp_first", page=True
        ).rows
    }

    tools: Counter[str] = Counter()
    files: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    mcp: Counter[str] = Counter()
    failed: Counter[str] = Counter()
    away: Counter[str] = Counter()
    shell = 0
    per: dict[str, dict[str, Any]] = {}
    internal = {n.lower() for n in INTERNAL_TOOLS}
    for sid, t, message, tool, server, path, cwd, program, host, machine in rows:
        if machine:
            devices.add(str(machine))
        s = per.setdefault(
            str(sid or "?"),
            {"start": t, "last": t, "machine": machine, "prompts": 0, "calls": 0, "failed": 0,
             "tools": Counter(), "files": set(), "hosts": set(), "cwd": cwd},
        )  # fmt: skip
        s["last"] = t
        s["cwd"] = s["cwd"] or cwd
        s["machine"] = s["machine"] or machine
        event = str(message or "")
        name = str(server or tool or "")
        if event.endswith("user_prompt_submit"):
            s["prompts"] += 1
        if not tool or str(tool).lower() in internal:
            continue
        if event.endswith("pre_tool_use"):
            s["calls"] += 1
            s["tools"][name] += 1
            tools[name] += 1
            if server:
                mcp[str(server)] += 1
            low = str(tool).lower()
            if low in WRITE_TOOLS and path:
                files[str(path)] += 1
                if outside(str(path), s["cwd"]):
                    away[str(path)] += 1
            if low in SHELL_TOOLS:
                shell += 1
                word = first_word(program)
                if word:
                    commands[word] += 1
            if path:
                s["files"].add(str(path))
            if host:
                s["hosts"].add(str(host))
                domains[str(host)] += 1
        elif event.endswith("post_tool_use_failure"):
            s["failed"] += 1
            failed[name] += 1

    for sid, s in sorted(per.items(), key=lambda kv: str(kv[1]["last"]), reverse=True):
        ranked = sorted(s["tools"].items(), key=lambda kv: (-kv[1], kv[0]))
        top = ", ".join(n for n, _ in ranked[:3])
        calls = f"{s['calls']} tool {'call' if s['calls'] == 1 else 'calls'}"
        parts = [
            f"{s['prompts']} {'prompt' if s['prompts'] == 1 else 'prompts'}",
            calls + (f" ({top})" if top else ""),
        ]
        if s["files"]:
            parts.append(f"{len(s['files'])} {'file' if len(s['files']) == 1 else 'files'}")
        if s["hosts"]:
            parts.append(f"{len(s['hosts'])} {'domain' if len(s['hosts']) == 1 else 'domains'}")
        if s["failed"]:
            parts.append(f"{s['failed']} failed")
        out.sessions.append(
            SessionLine(
                sid, str(s["machine"]) if s["machine"] else None, _iso(s["start"]) or "",
                _iso(s["last"]) or "", "; ".join(parts), bool(s["failed"]),
            )
        )  # fmt: skip

    out.tools, out.files, out.commands = _counts(tools), _counts(files), _counts(commands)
    out.domains, out.mcp = _counts(domains), _counts(mcp)
    out.devices = sorted(devices)

    # Flags.
    personal = [a for a in out.accounts if a.tier == "personal"]
    if personal:
        on = sorted({d for a in personal for d in a.devices})
        out.flags.append(
            Flag(
                "personal_account",
                "Personal Claude account on a machine sending to the company plugin",
                len(personal),
                [f"{a.email} on {', '.join(a.devices) or 'an unknown machine'}" for a in personal]
                if on else [str(a.email) for a in personal],
            )
        )  # fmt: skip
    if failed:
        out.flags.append(
            Flag("failed_calls", "Blocked or failed tool calls", sum(failed.values()),
                 [f"{n}: {c}" for n, c in failed.most_common(5)])
        )  # fmt: skip
    if away:
        out.flags.append(
            Flag("outside_folder", "Writes outside the session's working folder",
                 sum(away.values()), [p for p, _ in away.most_common(5)])
        )  # fmt: skip
    if shell:
        out.flags.append(
            Flag("shell", "Shell commands", shell, [w for w, _ in commands.most_common(5)])
        )
    new = sorted(m for m in mcp if firsts.get(m, "") >= out.start)
    if new:
        out.flags.append(Flag("new_mcp", "MCP servers first used in this range", len(new), new))
    out.sources = sorted(sources)
    return out
