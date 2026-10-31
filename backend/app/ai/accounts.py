"""Claude accounts seen by the hooks plugin, by tier (ADR-0030 amendment 2026-10-29).

The plugin reports the signed-in Claude account email; the device reports it, so it is a
tier below an Entra sign-in:

- Company, confirmed: a company-domain email, and an Entra sign-in to Claude by the same
  person within WINDOW before the account's last use.
- Company, reported: a company-domain email, and no Microsoft 365 sign-in source.
- Company, not confirmed: a company-domain email; sign-ins exist but none matched.
- Personal: an email outside the company domains.
- Not checked: no email reported (API key sessions), or no company domains set.

Company domains are the organization email domains (ADR-0018, T1). Nothing acts on a
tier (T5). Deterministic SQL on the caller's own view; no model is called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.sessions import _ONE_COPY, _a
from app.engine.duckdb import QueryEngine, QueryScope

TIMEOUT_S = 20.0
WINDOW = timedelta(days=30)  # C3: Claude's session lifetime
MAX_ACCOUNTS = 500

ACCOUNTS_SQL = f"""
WITH {_ONE_COPY}
SELECT lower(nullif(trim({_a("claude_account_email")}), '')) AS email,
       any_value({_a("account_from")}) AS account_from,
       list(DISTINCT device_hostname) FILTER (WHERE device_hostname IS NOT NULL) AS devices,
       list(DISTINCT {_a("os_user")}) FILTER (WHERE {_a("os_user")} IS NOT NULL) AS os_users,
       count(DISTINCT {_a("session_id")}) AS sessions,
       min(coalesce(time, time_observed)) AS first_seen,
       max(coalesce(time, time_observed)) AS last_seen
FROM hooks
GROUP BY 1
ORDER BY last_seen DESC
LIMIT {MAX_ACCOUNTS}"""  # noqa: S608  # fixed SQL text

# Successful Entra sign-ins to Claude, newest per person. The app is matched by name.
SIGNINS_SQL = """
SELECT lower(actor_user_name) AS who, max(coalesce(time, time_observed)) AS at
FROM events
WHERE template_id = 'm365_signin' AND status_id = 1
  AND (coalesce(resource_name, message) ILIKE '%claude%'
       OR coalesce(resource_name, message) ILIKE '%anthropic%')
GROUP BY 1"""

TIERS = ("company_confirmed", "company_reported", "company_unconfirmed", "personal", "not_checked")


@dataclass(slots=True)
class Account:
    email: str | None
    tier: str
    account_from: str | None
    devices: list[str]
    os_users: list[str]
    sessions: int
    first_seen: str | None
    last_seen: str | None
    # What matched, or what was looked for and not found (T4, C8).
    evidence: str


@dataclass(slots=True)
class Accounts:
    days: int
    domains_set: bool
    has_signins: bool
    rows: list[Account] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)


def _ts(v: Any) -> datetime | None:
    if v is None:
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace(" ", "T", 1))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _when(d: datetime) -> str:
    return d.strftime("%b %d, %H:%M UTC").replace(" 0", " ")


def tier(
    email: str | None,
    last: datetime | None,
    domains: list[str],
    has_signins: bool,
    signins: dict[str, datetime],
) -> tuple[str, str]:
    """(tier, evidence) for one account."""
    if not email:
        return "not_checked", "No Claude account reported (an API key session, or an older plugin)"
    if not domains:
        return "not_checked", "Organization email domains are not set"
    domain = email.rpartition("@")[2]
    if domain not in domains:
        return "personal", f"{domain} is not an organization domain"
    if not has_signins:
        return "company_reported", "Reported by the device; no Microsoft 365 sign-in source"
    at = signins.get(email)
    if at is not None and last is not None and last - WINDOW <= at <= last + timedelta(hours=1):
        return "company_confirmed", f"Entra sign-in to Claude {_when(at)}"
    return (
        "company_unconfirmed",
        "No Entra sign-in to Claude by this person in the 30 days before its last use",
    )


def accounts(
    engine: QueryEngine,
    allowed: list[str] | None,
    telemetry: list[str],
    m365: list[str],
    domains: list[str],
    now: datetime,
    days: int,
) -> Accounts:
    """`telemetry` and `m365` are the caller's readable sources of each kind."""
    start = now - timedelta(days=days)
    out = Accounts(days=days, domains_set=bool(domains), has_signins=bool(m365))
    if not telemetry:
        return out
    res = engine.run(
        ACCOUNTS_SQL, QueryScope(telemetry, start, now), timeout_s=TIMEOUT_S, name="accounts"
    )
    signins: dict[str, datetime] = {}
    sources = set(res.sources)
    if m365:
        found = engine.run(
            SIGNINS_SQL,
            QueryScope(m365, start - WINDOW, now),
            timeout_s=TIMEOUT_S,
            name="accounts.signins",
        )
        sources |= set(found.sources)
        signins = {str(w): t for w, at in found.rows if w and (t := _ts(at)) is not None}
    lowered = [d.lower() for d in domains]
    for email, src, devices, users, sessions, first, last in res.rows:
        last_t = _ts(last)
        which, why = tier(email, last_t, lowered, bool(m365), signins)
        first_t = _ts(first)
        out.rows.append(
            Account(
                email=str(email) if email else None,
                tier=which,
                account_from=str(src) if src else None,
                devices=sorted(str(d) for d in (devices or [])),
                os_users=sorted(str(u) for u in (users or [])),
                sessions=int(sessions or 0),
                first_seen=first_t.isoformat() if first_t else None,
                last_seen=last_t.isoformat() if last_t else None,
                evidence=why,
            )
        )
    out.counts = {k: sum(1 for r in out.rows if r.tier == k) for k in TIERS}
    out.sources = sorted(sources)
    return out
