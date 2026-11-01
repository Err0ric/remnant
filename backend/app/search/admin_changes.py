"""Microsoft 365 > Admin, read for what matters (owner, 2026-11-01).

On a tenant with directory sync, nearly every directory record is a sync or provisioning
cycle (an import or an execution every few minutes by a sync service), and the one real
change by an app is buried. Each change here is one row per operation (D122) with:

- who did it: a person, or an app by name. A Management API actor written
  `ServicePrincipal_<id>` is named from the directory audits in the window (the app that
  initiated a change, or a service principal a change targeted). No call to Microsoft:
  the connector's permissions stay as ADR-0002 lists them.
- what changed: the property names in the change details.
- provisioning: a sync or provisioning cycle by an app. The page groups these per service
  and day, and shows a failed cycle on its own.
- routine or not: role, policy, consent, credential, and user create, delete, or disable
  changes rank above routine updates, which the page hides by default.

Consents stay on the Apps tab (D122). Everything is SQL over `events`; no model is called.
"""

from __future__ import annotations

from app.search import drill

TS = drill.TS
OP = "lower(rtrim(trim(message), '.'))"
DIR = "template_id = 'm365_directory_audit'"
MGMT = (
    "template_id = 'm365_management_activity'"
    " AND json_extract_string(raw, '$.Workload') = 'AzureActiveDirectory'"
)
# Operations a sync or provisioning service runs on a cycle.
CYCLE_OPS = ("import", "export", "execution", "synchronization", "synchronize")
# Higher first; anything not listed is routine (0).
RANKS: tuple[tuple[int, str], ...] = (
    (5, "op LIKE '%role%'"),
    (4, "op LIKE '%policy%'"),
    (4, "op LIKE '%credential%' OR op LIKE '%certificates and secrets%'"),
    (4, "op LIKE 'add owner%' OR op LIKE 'add service principal%' OR op = 'add application'"),
    (3, "op IN ('add user', 'delete user', 'hard delete user', 'disable account',"
        " 'restore user', 'enable account', 'reset user password', 'reset password')"),
    (3, "list_contains(changed, 'AccountEnabled')"),
    (2, "op LIKE 'delete%' OR op LIKE 'remove%'"),
)  # fmt: skip
SP = r"^ServicePrincipal_([0-9A-Fa-f-]{36})$"


def _rank() -> str:
    cases = " ".join(f"WHEN {cond} THEN {n}" for n, cond in RANKS)
    return f"CASE {cases} ELSE 0 END"


ADMIN_SQL = (
    "WITH names AS (\n"  # noqa: S608  # fixed SQL text
    "  SELECT lower(id) AS id, any_value(name) AS name FROM (\n"
    "    SELECT json_extract_string(raw, '$.initiatedBy.app.servicePrincipalId') AS id,\n"
    "           json_extract_string(raw, '$.initiatedBy.app.displayName') AS name\n"
    f"    FROM events WHERE {DIR}\n"
    "    UNION ALL\n"
    "    SELECT unnest(json_extract_string(raw, '$.targetResources[*].id')),\n"
    "           unnest(json_extract_string(raw, '$.targetResources[*].displayName'))\n"
    f"    FROM events WHERE {DIR}\n"
    "      AND list_contains(json_extract_string(raw, '$.targetResources[*].type'),"
    " 'ServicePrincipal')\n"
    "  ) WHERE nullif(id, '') IS NOT NULL AND nullif(name, '') IS NOT NULL\n"
    "    AND name <> 'Unknown'\n"
    "  GROUP BY 1\n"
    "),\n"
    "r AS (\n"
    f"  SELECT {TS} AS ts, {OP} AS op, actor_user_name AS who, event_id, status_id,\n"
    "         coalesce(resource_name,\n"
    "                  json_extract_string(raw, '$.targetResources[0].userPrincipalName'),\n"
    "                  json_extract_string(raw, '$.targetResources[0].displayName')) AS target,\n"
    "         json_extract_string(raw, '$.initiatedBy.user.userPrincipalName') IS NULL AS by_app,\n"
    "         lower(json_extract_string(raw, '$.initiatedBy.app.servicePrincipalId')) AS app_id,\n"
    "         json_extract_string(raw, '$.loggedByService') AS service,\n"
    "         json_extract_string(raw, '$.targetResources[*].modifiedProperties[*].displayName')\n"
    "           AS changed,\n"
    "         coalesce(metadata_correlation_uid,\n"
    "                  coalesce(lower(actor_user_name), '') || '|'\n"
    f"                    || strftime({TS}, '%Y-%m-%d %H:%M')) AS k\n"
    f"  FROM events WHERE {DIR}\n"
    "  UNION ALL\n"
    f"  SELECT {TS}, {OP}, actor_user_name, event_id, status_id,\n"
    "         coalesce(resource_name, json_extract_string(raw, '$.ObjectId')),\n"
    "         NOT contains(coalesce(actor_user_name, ''), '@'),\n"
    f"         lower(regexp_extract(actor_user_name, '{SP}', 1)),\n"
    "         NULL,\n"
    "         json_extract_string(raw, '$.ModifiedProperties[*].Name'),\n"
    "         coalesce(metadata_correlation_uid,\n"
    "                  coalesce(lower(actor_user_name), '') || '|'\n"
    f"                    || strftime({TS}, '%Y-%m-%d %H:%M'))\n"
    f"  FROM events WHERE {MGMT}\n"
    "),\n"
    "g AS (\n"
    "  SELECT min(ts) AS time, op, any_value(who) AS who, bool_and(by_app) AS by_app,\n"
    "         any_value(nullif(app_id, '')) AS app_id, any_value(service) AS service,\n"
    "         any_value(target) AS target, max(status_id) AS status_id,\n"
    "         list(event_id) AS event_ids,\n"
    "         list_sort(list_distinct(flatten(list(coalesce(changed, []))))) AS changed\n"
    "  FROM r\n"
    "  WHERE op NOT IN ('userloggedin', 'userloginfailed')\n"
    "    AND op NOT LIKE 'consent to application%'\n"
    "  GROUP BY k, op\n"
    "  HAVING min(ts) >= TIMESTAMPTZ '{from}' AND min(ts) < TIMESTAMPTZ '{to}'\n"
    "),\n"
    "n AS (\n"
    "  SELECT g.*, names.name AS app_name FROM g LEFT JOIN names ON names.id = g.app_id\n"
    ")\n"
    "SELECT time,\n"
    "       CASE WHEN regexp_matches(coalesce(who, ''), '" + SP + "')\n"
    "            THEN coalesce(app_name, who) ELSE coalesce(who, app_name) END AS actor,\n"
    "       CASE WHEN by_app THEN 'app' ELSE 'person' END AS actor_kind, app_id,\n"
    "       op AS operation, target,\n"
    "       CASE WHEN status_id = 2 THEN 'Failure' ELSE 'Success' END AS status,\n"
    "       len(event_ids) AS events, event_ids,\n"
    "       array_to_string(changed, ', ') AS changed,\n"
    f"       by_app AND list_contains({list(CYCLE_OPS)}, op) AS provisioning,\n"
    "       coalesce(app_name, CASE WHEN regexp_matches(coalesce(who, ''), '"
    + SP
    + "') THEN NULL ELSE who END, service, who) AS service,\n"
    f"       {_rank()} AS rank\n"
    "FROM n\n"
    "ORDER BY rank DESC, time DESC"
)
