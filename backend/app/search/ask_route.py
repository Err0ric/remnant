"""Ask routing in code (ADR-0042 slice 1b): what a question names, which library queries
could answer it, and the SQL that runs once one is picked.

Nothing here calls a model. Time phrases, addresses, emails, and machine names are read
from the question by rules; library queries are ranked by the words they share with the
question; the chosen query runs through the guard on the asker's view like any query,
with the people, addresses, and machines the question named as bound parameters, never
written into the SQL.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.search.drill import lits
from app.search.identity import IdentityMap
from app.search.library import Library, LibraryQuery, Pack

Kind = Literal["user", "ip", "host", "service"]

IPV4 = re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b")
IPV6 = re.compile(r"(?<![\w:])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])", re.I)
EMAIL = re.compile(r"\b[\w.+-]{1,64}@[\w-]+(?:\.[\w-]+)+\b")
DOMAIN_USER = re.compile(r"\b[\w-]{1,32}\\[\w.$-]{1,64}")
# A machine name: letters and digits with a hyphen, digit, or dot inside (ws-0042,
# dc01.corp.internal); plain words are not machines.
HOST = re.compile(r"\b(?=[a-z0-9.-]*[0-9-])[a-z][a-z0-9-]{1,62}(?:\.[a-z0-9-]{1,63})*\b", re.I)
WORD = re.compile(r"[a-z0-9]+")
MAX_ENTITIES = 5
CANDIDATES = 8

STOP = frozenset(
    """a an and any are as at be by can did do does for from give had has have how i in is
    it list me my of on or show tell the there this those to was were what when where which
    who whom why with today yesterday week month hour hours day days last past since this
    all many much please""".split()
)
# Words people use for the same thing; ranking only (never SQL).
SAME = {
    "login": "signin", "logins": "signin", "logon": "signin", "logons": "signin",
    "signins": "signin", "sign": "signin", "authentication": "signin", "auth": "signin",
    "failed": "failure", "failures": "failure", "fail": "failure", "failing": "failure",
    "denied": "deny", "blocked": "deny", "refused": "deny", "dropped": "deny",
    "firewall": "paloalto", "palo": "paloalto", "pan": "paloalto",
    "vpn": "globalprotect", "address": "ip", "addresses": "ip", "source": "ip",
    "users": "user", "people": "user", "person": "user", "accounts": "user",
    "account": "user", "machines": "host", "hosts": "host", "devices": "host",
    "rules": "rule", "consents": "consent", "apps": "app", "applications": "app",
    "admins": "admin", "administrator": "admin", "domains": "domain", "names": "name",
}  # fmt: skip


def words(text: str) -> set[str]:
    return {SAME.get(w, w) for w in WORD.findall(text.lower()) if w not in STOP}


# --- time --------------------------------------------------------------------------------

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
LAST_N = re.compile(r"\b(?:last|past|previous)\s+(\d{1,3})\s+(minute|hour|day|week)s?\b")


@dataclass(frozen=True, slots=True)
class Span:
    start: datetime
    end: datetime
    label: str  # the phrase as understood: "today", "the last 6 hours"


def zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def parse_time(text: str, now: datetime, tz: str | None = None) -> Span | None:
    """The time a question names, in the asker's time zone; None when it names none."""
    t = text.lower()
    local = now.astimezone(zone(tz))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if m := LAST_N.search(t):
        n, unit = int(m.group(1)), m.group(2)
        step = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1),
                "day": timedelta(days=1), "week": timedelta(weeks=1)}[unit]  # fmt: skip
        if n:
            return Span(now - n * step, now, f"the last {n} {unit}{'s' if n != 1 else ''}")
    if re.search(r"\b(?:last|past) 24 hours\b|\b(?:last|past) day\b", t):
        return Span(now - timedelta(hours=24), now, "the last 24 hours")
    if re.search(r"\b(?:last|past) hour\b", t):
        return Span(now - timedelta(hours=1), now, "the last hour")
    if re.search(r"\byesterday\b", t):
        return Span(midnight - timedelta(days=1), midnight, "yesterday")
    if re.search(r"\b(?:today|so far today|this morning)\b", t):
        return Span(midnight, now, "today")
    if re.search(r"\bthis week\b", t):
        return Span(midnight - timedelta(days=local.weekday()), now, "this week")
    if re.search(r"\blast week\b", t):
        start = midnight - timedelta(days=local.weekday() + 7)
        return Span(start, start + timedelta(days=7), "last week")
    if re.search(r"\b(?:last|past) (?:7 days|seven days)\b", t):
        return Span(now - timedelta(days=7), now, "the last 7 days")
    if re.search(r"\bthis month\b", t):
        return Span(midnight.replace(day=1), now, "this month")
    if re.search(r"\b(?:last|past) month\b|\b(?:last|past) 30 days\b", t):
        return Span(now - timedelta(days=30), now, "the last 30 days")
    if m := re.search(r"\bsince (" + "|".join(DAYS) + r")\b", t):
        back = (local.weekday() - DAYS.index(m.group(1))) % 7
        return Span(midnight - timedelta(days=back), now, f"since {m.group(1).capitalize()}")
    return None


# --- entities ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Entity:
    kind: Kind
    value: str


def find_entities(text: str, people: set[str] | None = None) -> list[Entity]:
    """Addresses, people, and machines the question names, in order, at most 5. `people`
    are known person keys (the identity map), so a bare "dana" is a person too."""
    out: list[Entity] = []
    taken: list[tuple[int, int]] = []

    def add(kind: Kind, m: re.Match[str]) -> None:
        if any(m.start() < b and a < m.end() for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        out.append(Entity(kind, m.group(0).rstrip(".")))

    for m in EMAIL.finditer(text):
        add("user", m)
    for m in DOMAIN_USER.finditer(text):
        add("user", m)
    for m in IPV4.finditer(text):
        add("ip", m)
    for m in IPV6.finditer(text):
        try:
            ipaddress.IPv6Address(m.group(0))
        except ValueError:
            continue
        add("ip", m)
    for m in HOST.finditer(text):
        if not m.group(0).replace(".", "").isdigit():
            add("host", m)
    if people:
        for m in WORD.finditer(text.lower()):
            if m.group(0) in people:
                add("user", m)
    out.sort(key=lambda e: text.find(e.value))
    return out[:MAX_ENTITIES]


# --- library candidates ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    pack: Pack
    query: LibraryQuery
    score: float

    @property
    def ref(self) -> str:
        return f"{self.pack.id}/{self.query.id}"


def _text(q: LibraryQuery) -> str:
    # Ranking reads the name, tags, group, and example phrasings; never sent anywhere.
    return " ".join([q.name, q.group, " ".join(q.tags), " ".join(q.ask), q.description])


def rank(question: str, library: Library, seen: set[str], top: int = CANDIDATES) -> list[Candidate]:
    """Library queries offered to this viewer (their templates have events), best first,
    by the share of the question's words each one covers. Zero-score queries are left
    out."""
    want = words(question)
    if not want:
        return []
    out = []
    for pack in library.packs:
        for q in pack.queries:
            if not Library.offered(q, seen):
                continue
            have = words(_text(q))
            hits = want & have
            if not hits:
                continue
            phrase = max((len(want & words(a)) for a in q.ask), default=0)
            score = len(hits) / len(want) + 0.5 * phrase / len(want)
            out.append(Candidate(pack, q, round(score, 3)))
    out.sort(key=lambda c: (-c.score, c.ref))
    return out[:top]


# --- the SQL that runs -------------------------------------------------------------------

# Output column names a library query uses for each kind of entity (as the UI links them).
COLUMNS: dict[Kind, tuple[str, ...]] = {
    "user": ("user", "user_name", "username", "person", "who", "actor_user_name", "account"),
    "ip": ("address", "ip", "client", "src_ip", "src_endpoint_ip", "client_ip"),
    "host": ("host", "hostname", "device", "machine", "device_hostname"),
    "service": ("service_id", "service"),
}


@dataclass(slots=True)
class Plan:
    sql: str  # library SQL, wrapped with the question's filters
    params: dict[str, str | int | float | bool]
    filters: list[str] = field(default_factory=list)  # "user = dana", for How I got this
    unused: list[Entity] = field(default_factory=list)  # named, but the query cannot filter


def _quote(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def plan(
    q: LibraryQuery,
    columns: list[str],
    entities: list[Entity],
    params: dict[str, str | int | float | bool],
    ident: IdentityMap | None = None,
) -> Plan:
    """The library query with each named entity as a filter on the output column of its
    kind, bound as parameters. A person matches every name the identity map gives them.
    Entities the output has no column for are reported, not dropped silently."""
    lower = {c.lower(): c for c in columns}
    where: list[str] = []
    values: dict[str, str | int | float | bool] = dict(params)
    out = Plan("", values)
    for i, e in enumerate(entities):
        col = next((lower[n] for n in COLUMNS[e.kind] if n in lower), None)
        if col is None:
            out.unused.append(e)
            continue
        if e.kind == "user":
            keys = ident.keys_for(e.value) if ident else [e.value.lower()]
            # An email also matches its bare login (alice@example.com and alice), as people
            # are named both ways across sources; the filter line says so.
            local = e.value.lower().rpartition("\\")[2].partition("@")[0]
            if local and local not in keys:
                keys = [*keys, local]
            names = []
            for j, k in enumerate(keys[:20]):
                values[f"ask_user_{i}_{j}"] = k
                names.append("{{" + f"ask_user_{i}_{j}" + "}}")
            domains = lits(ident.domains if ident and ident.domains else [""])
            key = (
                f"regexp_replace(lower(trim(CAST({_quote(col)} AS VARCHAR))), '^[^\\\\@]*\\\\', '')"
            )
            key = (
                f"(CASE WHEN list_contains({domains}, split_part({key}, '@', 2))"
                f" THEN split_part({key}, '@', 1) ELSE {key} END)"
            )
            where.append(f"{key} IN ({', '.join(names)})")
        else:
            values[f"ask_{e.kind}_{i}"] = e.value
            where.append(f"lower(CAST({_quote(col)} AS VARCHAR)) = lower({{{{ask_{e.kind}_{i}}}}})")
        shown = (
            e.value
            if e.kind != "user" or len(keys) == 1
            else f"{e.value} (also {', '.join(k for k in keys if k != e.value.lower())})"
        )
        out.filters.append(f"{col} = {shown}")
    # Library SQL from a reviewed pack; columns quoted; every value a bound parameter.
    wrapped = f"SELECT * FROM (\n{q.sql}\n) AS library_query\nWHERE "  # noqa: S608
    out.sql = q.sql if not where else wrapped + "\n  AND ".join(where)
    out.params = values
    return out
