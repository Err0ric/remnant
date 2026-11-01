"""Microsoft 365 app consents, counted once (F66).

Graph (directory audit) and the Management Activity API both report the same consent, so
a consent is one row per operation: the shared correlation id when a record has one, else
the person and the minute, plus the operation name ("Consent to application." and
"Consent to application" are the same). A consent with status 2 was blocked (a policy or
admin consent requirement stopped it); every other consent was granted.

Graph often writes "Unknown" for the app. Its name then comes from the app id's other
records, else from the person's Microsoft 365 sign-in up to 60 seconds before: the
consent prompt follows the sign-in to the app.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

FILL_S = 60  # a sign-in this close before the consent names the app

# One consent (D122): the shared correlation id, else the person and the minute, with the
# operation. The Microsoft 365 rollup keeps the same key per closed day (ADR-0041).
OP = "lower(rtrim(trim(message), '.'))"
KEY = """coalesce(metadata_correlation_uid,
                  coalesce(lower(actor_user_name), '') || '|'
                    || strftime(coalesce(time, time_observed), '%Y-%m-%d %H:%M'))"""
WHERE = """template_id IN ('m365_directory_audit', 'm365_management_activity')
    AND message ILIKE 'Consent to application%'"""
# A copy that says granted wins over one with no result; applied again over the rollup's
# per-day values, it gives the same answer.
STATUS = "coalesce(min(status_id) FILTER (WHERE status_id = 1), max(status_id))"

# The consent rows, one per operation, with the app filled. Fixed text; times are
# parameters. Ends in a SELECT from `consents` so callers can count or list.
CONSENTS_CTE = f"""
raw AS (
  SELECT coalesce(time, time_observed) AS ts, nullif(actor_user_name, '') AS who,
         status_id, nullif(nullif(resource_name, ''), 'Unknown') AS app, resource_uid,
         privileges, status_detail, event_id,
         {OP} AS op,
         {KEY} AS k
  FROM events
  WHERE {WHERE}
),
one AS (
  SELECT min(ts) AS ts, any_value(who) AS who,
         {STATUS} AS status_id,
         max(app) AS app, max(resource_uid) AS app_id, max(privileges) AS privileges,
         max(status_detail) AS reason, min(event_id) AS event_id,
         list(event_id ORDER BY event_id) AS event_ids
  FROM raw
  GROUP BY k, op
),
names AS (
  SELECT resource_uid AS app_id, max(nullif(nullif(resource_name, ''), 'Unknown')) AS app
  FROM events
  WHERE template_id IN ('m365_directory_audit', 'm365_management_activity', 'm365_signin')
    AND resource_uid IS NOT NULL
  GROUP BY 1
),
signins AS (
  -- Sign-ins stored before m365_signin 1.1.0 have no resource_name; their message is the
  -- app's display name (the template's message), so it names the app for them.
  SELECT lower(actor_user_name) AS who_l, coalesce(time, time_observed) AS ts,
         nullif(nullif(coalesce(resource_name, message), ''), 'Unknown') AS app
  FROM events
  WHERE template_id = 'm365_signin' AND actor_user_name IS NOT NULL
    AND nullif(nullif(coalesce(resource_name, message), ''), 'Unknown') IS NOT NULL
),
consents AS (
  SELECT o.ts, o.who, o.status_id, o.app_id, o.privileges, o.reason, o.event_id,
         o.event_ids,
         coalesce(o.app, n.app,
                  CASE WHEN epoch(o.ts) - epoch(s.ts) <= {FILL_S} THEN s.app END) AS app
  FROM one o
  LEFT JOIN names n ON n.app_id = o.app_id
  ASOF LEFT JOIN signins s ON s.who_l = lower(o.who) AND o.ts >= s.ts
)"""  # noqa: S608  # fixed SQL text

# Granted now and before, blocked now, and the newest of each.
COUNTS_SQL = f"""
WITH {CONSENTS_CTE}
SELECT
  count(*) FILTER (WHERE coalesce(status_id, 1) <> 2 AND ts >= $start),
  count(*) FILTER (WHERE coalesce(status_id, 1) <> 2 AND ts < $start),
  count(*) FILTER (WHERE status_id = 2 AND ts >= $start),
  arg_max(struct_pack(app := app, who := who, scopes := privileges), ts)
    FILTER (WHERE coalesce(status_id, 1) <> 2 AND ts >= $start),
  arg_max(struct_pack(app := app, who := who, scopes := privileges), ts)
    FILTER (WHERE status_id = 2 AND ts >= $start)
FROM consents"""  # noqa: S608  # fixed SQL text


def rows_sql(blocked: bool, start: datetime) -> str:
    """Search SQL listing the consents behind a card, one row per consent."""
    cond = "status_id = 2" if blocked else "coalesce(status_id, 1) <> 2"
    since = start.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"WITH {CONSENTS_CTE.strip()}\n"
        "SELECT ts AS time, who AS person, app, app_id, privileges AS permissions,"
        " reason, event_id, event_ids\n"
        f"FROM consents\nWHERE {cond} AND ts >= TIMESTAMPTZ '{since}+00'\n"
        "ORDER BY ts DESC"
    )


def drill_sql(blocked: bool) -> str:
    """rows_sql for a Dashboard drill-through: the window's bounds are `{from}` and `{to}`,
    filled in by the page (ADR-0039)."""
    cond = "status_id = 2" if blocked else "coalesce(status_id, 1) <> 2"
    return (
        f"WITH {CONSENTS_CTE.strip()}\n"
        "SELECT ts AS time, who AS person, app, app_id, privileges AS permissions,"
        " reason, event_id, event_ids\n"
        f"FROM consents\nWHERE {cond}\n"
        "  AND ts >= TIMESTAMPTZ '{from}' AND ts < TIMESTAMPTZ '{to}'\n"
        "ORDER BY ts DESC"
    )


def describe(latest: Any) -> str:
    """'Lab Notes App (User.Read, Mail.Read) by sam@example.com'."""
    if not isinstance(latest, dict):
        return ""
    app = latest.get("app") or "an app with no name"
    scopes = str(latest.get("scopes") or "").split()
    shown = ", ".join(scopes[:3]) + (f" +{len(scopes) - 3}" if len(scopes) > 3 else "")
    who = latest.get("who")
    return f"{app}{f' ({shown})' if shown else ''}{f' by {who}' if who else ''}"
