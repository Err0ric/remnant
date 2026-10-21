"""One person under several names (ADR-0018 rows 1 to 6).

A name's *key* is deterministic: lower case, trimmed, any `DOMAIN\\` prefix removed, and an
address in an organization domain reduced to its local part. Aliases the administrator
set (by hand or by accepting a suggestion) then map a key to a person. Nothing stored
changes: this is applied when Investigations and AI usage read events.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ParamInvalidError
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


class IdentityStore:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

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
        now = datetime.now(UTC).isoformat()
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
                (a, person.strip()[:NAME_MAX], actor, datetime.now(UTC).isoformat()),
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
