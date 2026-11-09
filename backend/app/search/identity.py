"""One person under several names (ADR-0018 rows 1 to 6).

A name's *key* is deterministic: lower case, trimmed, any `DOMAIN\\` prefix removed, and an
address in an organization domain reduced to its local part. Aliases the administrator
set (by hand or by accepting a suggestion) then map a key to a person. Nothing stored
changes: this is applied when Investigations and AI usage read events.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core import clock
from app.core.errors import ParamInvalidError
from app.core.schema import COLUMNS_BY_NAME
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.db import MetaDB

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
NAME_MAX = 256
MAX_DOMAINS = 20
MAX_ALIASES = 5000
# Names that are roles, not people; never part of a same-machine suggestion.
NOT_PEOPLE = frozenset(
    {
        "root", "admin", "administrator", "system", "guest", "nobody", "daemon", "local service",
        "network service", "anonymous", "user", "test", "ubuntu", "oracle", "postgres", "www-data",
    }
)  # fmt: skip


def _strip(name: str) -> str:
    s = name.strip().lower()
    return re.sub(r"^[^\\@]*\\", "", s)  # DOMAIN\user -> user


def key_of(name: str, domains: list[str]) -> str:
    s = _strip(name)
    local, at, domain = s.partition("@")
    return local if at and domain in domains else s


def identity_values(
    sql: str,
    store: IdentityStore | None,
    engine: QueryEngine | None = None,
    scope: QueryScope | None = None,
    viewer: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """The Identities values a query needs at run time, or none when it uses neither
    placeholder. Only the part of the map the caller's own events show is bound (T70,
    D219): an alias whose account is in the scanned columns of `scope`, and an
    organization domain one of those accounts is in. A guess at an account the caller
    cannot read is its own person. An administrator (`role`) gets the whole map, with no
    scan: the Identities page shows it to them anyway (D223). Without a store (a test
    app), or without the engine and scope to check against, nothing is bound: every name
    is its own person. Only the
    values the SQL reads are returned: `{{org_domains}}` alone binds `id_org`, not the
    alias lists (DuckDB refuses a parameter the statement does not use)."""
    from app.search.params import PERSON, uses_identities

    if not uses_identities(sql):
        return {}
    people = PERSON.findall(sql)
    if store is not None and role == "admin":
        found = store.load()
    elif store is None or engine is None or scope is None:
        found = IdentityMap()
    else:
        columns = {"actor_user_name"} | {c for c in people if c in COLUMNS_BY_NAME}
        found = store.scoped(engine, scope, sorted(columns), viewer, role)
    values = found.sql_values()
    return values if people else {"id_org": values["id_org"]}


SEEN_NAME = "SELECT DISTINCT CAST({c} AS VARCHAR) AS raw FROM events WHERE {c} IS NOT NULL"
SEEN_SQL = """
WITH r AS ({names}),
n AS (SELECT DISTINCT regexp_replace(lower(trim(raw)), '^[^\\\\@]*\\\\', '') AS u FROM r),
k AS (
  SELECT split_part(u, '@', 2) AS d, position('@' IN u) > 0 AS mail,
         CASE WHEN list_contains($seen_org, split_part(u, '@', 2))
              THEN split_part(u, '@', 1) ELSE u END AS k
  FROM n
)
SELECT DISTINCT 'd' AS kind, d AS v FROM k WHERE mail AND list_contains($seen_org, d)
UNION
SELECT DISTINCT 'k', k FROM k WHERE k IN (SELECT unnest($seen_keys))"""


def key_sql(col: str) -> str:
    """The same key in SQL; needs the `$id_org` list parameter (see IdentityMap.params)."""
    k = f"regexp_replace(lower(trim({col})), '^[^\\\\@]*\\\\', '')"
    return (
        f"(CASE WHEN list_contains($id_org, split_part({k}, '@', 2))"
        f" THEN split_part({k}, '@', 1) ELSE {k} END)"
    )


def is_person(key: str) -> bool:
    return (
        bool(key) and key not in NOT_PEOPLE and not key.endswith("$") and not key.startswith("svc")
    )


@dataclass(slots=True)
class IdentityMap:
    domains: list[str] = field(default_factory=list)  # first is used to show bare people
    aliases: dict[str, str] = field(default_factory=dict)  # key -> person key
    email_people: set[str] = field(default_factory=set)  # person keys given as org emails

    def params(self) -> dict[str, Any]:
        return {"id_org": self.domains or [""]}

    def sql_values(self) -> dict[str, Any]:
        """The values `{{person:...}}` and `{{org_domains}}` read (params.IDENTITY_PARAMS):
        the organization domains and the alias table as two lists. Loaded per run, so a
        query sees the links as they are when it runs. Empty lists hold one blank, which
        matches only a blank name (and a blank name is never a person)."""
        pairs = sorted(self.aliases.items())
        return {
            "id_org": self.domains or [""],
            "id_from": [a for a, _ in pairs] or [""],
            "id_to": [p for _, p in pairs] or [""],
        }

    def within(self, engine: QueryEngine, scope: QueryScope, columns: list[str]) -> IdentityMap:
        """The part of this map that `scope` shows in `columns` (fixed schema names): the
        aliases whose account is there and the organization domains of accounts there.
        One scan per run of a query that uses Identities; none when the map is empty."""
        if not self.domains and not self.aliases:
            return self
        names = "\nUNION\n".join(SEEN_NAME.format(c=c) for c in columns)
        res = engine.run(
            SEEN_SQL.format(names=names),
            scope,
            {"seen_org": self.domains or [""], "seen_keys": sorted(self.aliases) or [""]},
            row_cap=MAX_ALIASES + MAX_DOMAINS,
            timeout_s=20,
            intel=False,
            name="identities.scope",
        )
        seen = {(str(kind), str(v)) for kind, v in res.rows}
        domains = [d for d in self.domains if ("d", d) in seen]
        return IdentityMap(
            domains=domains,
            aliases={a: p for a, p in self.aliases.items() if ("k", a) in seen},
            email_people=self._email_people_for(domains),
        )

    def seen_in(self, names: Iterable[str]) -> IdentityMap:
        """The part of this map that `names` show: names read from the caller's own rows
        (the events view), never a name the caller typed. The aliases whose account is
        one of them and the organization domains one of them is in, as `within` keeps
        from a scan; for a page that already holds the rows, so no scan is needed."""
        if not self.domains and not self.aliases:
            return self.copy()
        doms: set[str] = set()
        keys: set[str] = set()
        for n in names:
            if self.org_email(n):
                doms.add(_strip(n).partition("@")[2])
            keys.add(key_of(n, self.domains))
        kept = [d for d in self.domains if d in doms]
        return IdentityMap(
            domains=kept,
            aliases={a: p for a, p in self.aliases.items() if a in keys},
            email_people=self._email_people_for(kept),
        )

    def _email_people_for(self, domains: list[str]) -> set[str]:
        """People given as an organization address are shown in the first domain
        (`display`); kept only while that domain is still the first one, else such a
        person would be shown in a domain they were not given in."""
        same = bool(domains) and bool(self.domains) and domains[0] == self.domains[0]
        return set(self.email_people) if same else set()

    def fingerprint(self) -> tuple[Any, ...]:
        """The map's content, so a kept scoped set is never used after Identities change."""
        return (
            tuple(self.domains), tuple(sorted(self.aliases.items())),
            tuple(sorted(self.email_people)),
        )  # fmt: skip

    def copy(self) -> IdentityMap:
        return IdentityMap(list(self.domains), dict(self.aliases), set(self.email_people))

    def key(self, name: str) -> str:
        k = key_of(name, self.domains)
        return self.aliases.get(k, k)

    def keys_for(self, person: str) -> list[str]:
        """Every key that counts as this person: its own, and aliases pointing at it."""
        target = self.key(person)
        out = {target} | {a for a, p in self.aliases.items() if p == target}
        return sorted(out)

    def display(self, key: str, seen_as_email: bool) -> str:
        """The email form in the first organization domain for someone seen with an
        organization address; the key otherwise (a bare login is never given a domain it
        was not seen with)."""
        if (seen_as_email or key in self.email_people) and self.domains and "@" not in key:
            return f"{key}@{self.domains[0]}"
        return key

    def org_email(self, name: str) -> bool:
        s = _strip(name)
        _, at, domain = s.partition("@")
        return bool(at) and domain in self.domains


SCOPED_TTL_S = 60.0  # as the page cache
SCOPED_MAX = 256


@dataclass(frozen=True, slots=True)
class _Kept:
    start: datetime | None
    end: datetime | None
    at: float
    found: IdentityMap


def _inside(scope: QueryScope) -> QueryScope:
    """The range scanned for a kept set: the asked range with its ends moved inward to
    whole minutes, so calls seconds apart (the top bar lookup's moving 30 days, a search
    run again) find the same kept set. Narrower, so never an alias the asked range does
    not show; an account seen only in an end's partial minute stays its own person."""
    start, end = scope.start, scope.end
    if start is not None and (start.second or start.microsecond):
        start = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if end is not None:
        end = end.replace(second=0, microsecond=0)
    if start is not None and end is not None and start >= end:
        return scope
    return QueryScope(scope.sources, start, end)


def _contains(scope: QueryScope, kept: _Kept) -> bool:
    """The requested range holds the kept one (None is open). The kept set then read
    fewer events than a fresh scan would, so it is the same or smaller: never an alias the
    requested range does not show."""
    starts = scope.start is None or (kept.start is not None and scope.start <= kept.start)
    ends = scope.end is None or (kept.end is not None and kept.end <= scope.end)
    return starts and ends


class ScopedIdentities:
    """The part of Identities a caller's scope shows (T70, D219), kept for a minute so a
    page's calls (the person page asks for summary, risk, and graph at once) share one
    scan. Kept per viewer and role, per exact source list (a grant change is a new
    list), per columns, and per Identities content (any change is a new entry); reused only for a
    range that contains the one scanned. Concurrent callers with the same key wait for
    the one scan in flight."""

    def __init__(
        self, ttl_s: float = SCOPED_TTL_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: dict[tuple[Any, ...], list[_Kept]] = {}
        self._flight: dict[tuple[Any, ...], threading.Lock] = {}

    def get(
        self,
        m: IdentityMap,
        engine: QueryEngine,
        scope: QueryScope,
        columns: list[str],
        viewer: str | None,
        role: str | None = None,
    ) -> IdentityMap:
        if not m.domains and not m.aliases:
            return m.copy()
        if viewer is None:  # no one to keep it for
            return m.within(engine, scope, columns)
        sources = None if scope.sources is None else tuple(sorted(scope.sources))
        # The role is part of the key: a role change is a new entry (D223).
        key = (viewer, role, sources, tuple(sorted(columns)), m.fingerprint())
        hit = self._find(key, scope)
        if hit is not None:
            return hit
        scope = _inside(scope)  # what is scanned: never wider than asked
        hit = self._find(key, scope)
        if hit is not None:
            return hit
        with self._lock:
            flight = self._flight.setdefault(key, threading.Lock())
        with flight:
            hit = self._find(key, scope)
            if hit is not None:
                return hit
            found = m.within(engine, scope, columns)
            with self._lock:
                if len(self._kept) >= SCOPED_MAX and key not in self._kept:
                    self._prune()
                entries = self._kept.setdefault(key, [])
                entries.append(_Kept(scope.start, scope.end, self._clock(), found.copy()))
                del entries[:-4]
            return found

    def _find(self, key: tuple[Any, ...], scope: QueryScope) -> IdentityMap | None:
        now = self._clock()
        with self._lock:
            for kept in reversed(self._kept.get(key, [])):
                if now - kept.at < self._ttl and _contains(scope, kept):
                    return kept.found.copy()
        return None

    def _prune(self) -> None:
        now = self._clock()
        for k in [k for k, v in self._kept.items() if all(now - e.at >= self._ttl for e in v)]:
            del self._kept[k]
            self._flight.pop(k, None)
        while len(self._kept) >= SCOPED_MAX:
            k = next(iter(self._kept))
            del self._kept[k]
            self._flight.pop(k, None)


class IdentityStore:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta
        self._scoped = ScopedIdentities()

    def scoped(
        self,
        engine: QueryEngine,
        scope: QueryScope,
        columns: list[str],
        viewer: str | None,
        role: str | None = None,
    ) -> IdentityMap:
        """The part of the map `viewer`'s scope shows in `columns` (T70, D219). An
        administrator gets the whole map with no scan, since the Identities page shows it
        to them (D223); every other role is scoped, holding every source group or not."""
        m = self.load()
        if role == "admin":
            return m
        return self._scoped.get(m, engine, scope, columns, viewer, role)

    def load(self) -> IdentityMap:
        with self._meta.connect() as con:
            domains = [
                str(r[0])
                for r in con.execute("SELECT domain FROM identity_domains ORDER BY position")
            ]
            rows = con.execute("SELECT alias, person FROM identity_aliases").fetchall()
        m = IdentityMap(domains=domains)
        for alias, person in rows:
            target = key_of(str(person), domains)
            m.aliases[key_of(str(alias), domains)] = target
            if m.org_email(str(person)):
                m.email_people.add(target)
        return m

    def aliases(self) -> list[dict[str, str]]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT alias, person, created_by, created_at FROM identity_aliases"
                " ORDER BY person, alias"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_domains(self, domains: list[str], actor: str) -> list[str]:
        clean: list[str] = []
        for d in domains:
            d = d.strip().lower().lstrip("@")
            if not DOMAIN_RE.fullmatch(d):
                raise ParamInvalidError(f"Not a domain name: {d[:80]!r}")
            if d not in clean:
                clean.append(d)
        if len(clean) > MAX_DOMAINS:
            raise ParamInvalidError(f"At most {MAX_DOMAINS} organization domains")
        now = clock.now().isoformat()
        with self._meta.connect() as con:
            con.execute("DELETE FROM identity_domains")
            con.executemany(
                "INSERT INTO identity_domains (domain, position, added_by, added_at)"
                " VALUES (?, ?, ?, ?)",
                [(d, i, actor, now) for i, d in enumerate(clean)],
            )
        return clean

    def set_alias(self, alias: str, person: str | None, actor: str) -> None:
        a = alias.strip()
        if not a or len(a) > NAME_MAX or (person is not None and not person.strip()):
            raise ParamInvalidError("Give the name and the person it belongs to")
        domains = self.load().domains
        if person is not None and key_of(a, domains) == key_of(person, domains):
            raise ParamInvalidError("These names already count as the same person")
        with self._meta.connect() as con:
            if person is None:
                con.execute("DELETE FROM identity_aliases WHERE lower(alias) = lower(?)", (a,))
                return
            n = con.execute("SELECT count(*) FROM identity_aliases").fetchone()[0]
            if n >= MAX_ALIASES:
                raise ParamInvalidError(f"At most {MAX_ALIASES} aliases")
            con.execute("DELETE FROM identity_aliases WHERE lower(alias) = lower(?)", (a,))
            con.execute(
                "INSERT INTO identity_aliases (alias, person, created_by, created_at)"
                " VALUES (?, ?, ?, ?)",
                (a, person.strip()[:NAME_MAX], actor, clock.now().isoformat()),
            )


# --- suggestions (ADR-0018 row 4) ----------------------------------------------------------

DOMAIN_SQL = """
WITH n AS (
  SELECT DISTINCT regexp_replace(lower(trim(actor_user_name)), '^[^\\\\@]*\\\\', '') AS u
  FROM events WHERE nullif(trim(actor_user_name), '') IS NOT NULL
),
bare AS (SELECT u FROM n WHERE position('@' IN u) = 0),
mail AS (
  SELECT split_part(u, '@', 1) AS l, split_part(u, '@', 2) AS d FROM n
  WHERE position('@' IN u) > 0
)
SELECT d, count(*) AS addresses,
       count(*) FILTER (WHERE l IN (SELECT u FROM bare)) AS shared,
       list_slice(list(l ORDER BY l) FILTER (WHERE l IN (SELECT u FROM bare)), 1, 5) AS examples
FROM mail
WHERE NOT list_contains($id_org, d)
GROUP BY d HAVING count(*) FILTER (WHERE l IN (SELECT u FROM bare)) > 0
ORDER BY shared DESC, d
LIMIT 20"""

HOST_SQL = """
SELECT device_hostname, list(DISTINCT lower(trim(actor_user_name)))
FROM events
WHERE nullif(trim(device_hostname), '') IS NOT NULL
  AND nullif(trim(actor_user_name), '') IS NOT NULL
GROUP BY 1
HAVING count(DISTINCT lower(trim(actor_user_name))) <= 8
LIMIT 5000"""


@dataclass(slots=True)
class DomainSuggestion:
    domain: str
    addresses: int
    shared: int
    examples: list[str]


@dataclass(slots=True)
class AliasSuggestion:
    alias: str
    person: str
    hosts: list[str]


def suggestions(
    engine: QueryEngine, scope: QueryScope, m: IdentityMap
) -> tuple[list[DomainSuggestion], list[AliasSuggestion]]:
    doms = [
        DomainSuggestion(str(d), int(a), int(s), [str(x) for x in ex or []])
        for d, a, s, ex in engine.run(DOMAIN_SQL, scope, m.params(), timeout_s=20).rows
    ]
    pairs: dict[tuple[str, str], list[str]] = {}
    for host, names in engine.run(HOST_SQL, scope, timeout_s=20).rows:
        keys = {m.key(str(n)) for n in names or []}
        people = [k for k in keys if is_person(k)]
        mail = [k for k in people if "@" in k]
        other = [k for k in people if "@" not in k]
        if len(mail) == 1 and len(other) == 1:
            pairs.setdefault((other[0], mail[0]), []).append(str(host))
    aliases = [
        AliasSuggestion(alias=a, person=p, hosts=sorted(h)[:5])
        for (a, p), h in sorted(pairs.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ][:50]
    return doms, aliases
