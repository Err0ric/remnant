"""Inbox rules read for what they do (owner, 2026-10-31; SPEC D132).

A person who files mail from coworkers into department folders creates dozens of rules;
counting every rule as suspicious buried the two that moved mail to Junk. Each New-InboxRule,
Set-InboxRule, UpdateInboxRules, and forwarding Set-Mailbox record is read for its settings
(the Management Activity record's `Parameters`, or `OperationProperties` from Outlook) and
classed:

- forwarding: forwards or redirects mail; external when a recipient's domain is not the
  person's own.
- deleting: deletes the message.
- hiding: moves it to Junk Email, RSS Feeds, Archive, Conversation History, or Deleted
  Items, or marks it read and moves it (inbox rules that hide mail, T1564.008).
- organizing: moves it to any other named folder.
- other: none of these (a category, a flag, settings Microsoft did not record).

Only hiding, deleting, and external forwarding are risky. A risky rule is high severity
when it watches for money or sign-in words (invoice, payment, wire, password, MFA, bank,
payroll) or mail from finance, IT, security, or leadership addresses (business email
compromise hides replies this way). Everything here is SQL over `events`; no model is
called.
"""

from __future__ import annotations

from app.search.dashboard import forwarding, mail_rules

TS = "coalesce(time, time_observed)"
OP = "lower(rtrim(trim(message), '.'))"
_PAIRS = '[{"Name":"VARCHAR","Value":"VARCHAR"}]'
# Name and value pairs of the record, from either shape Microsoft writes.
_PS = (
    f"list_concat(coalesce(TRY(from_json(json_extract(raw, '$.Parameters'), '{_PAIRS}')), []),"
    f" coalesce(TRY(from_json(json_extract(raw, '$.OperationProperties'), '{_PAIRS}')), []))"
)
HIDDEN_FOLDERS = (
    "junk email",
    "junk e-mail",
    "junk",
    "rss feeds",
    "rss subscriptions",
    "archive",
    "conversation history",
    "deleted items",
)
MONEY_WORDS = r"invoice|payment|wire|password|mfa|bank|payroll"
SENSITIVE_SENDERS = (
    r"finance|accounting|accounts?payable|payroll|billing|treasury|^ap@|"
    r"^it@|helpdesk|servicedesk|security|^ceo|^cfo|^cio|^ciso|president|executive"
)
WHERE = f"template_id = 'm365_management_activity' AND ({mail_rules(OP)} OR {forwarding(OP)})"


def _p(*names: str) -> str:
    """The first of these settings the record has (names in lower case)."""
    picks = [
        f"list_any_value(list_transform(list_filter(ps, x -> lower(x.Name) = '{n}'), x -> x.Value))"
        for n in names
    ]
    return f"coalesce({', '.join(picks)})" if len(picks) > 1 else picks[0]


# The rules with their settings and class, one row per record (Exchange writes each
# change once, D122). Ends in `rules`; fixed text, so callers add their own WHERE.
RULES_CTE = f"""
r0 AS (
  SELECT source_id, {TS} AS time, actor_user_name AS person, {OP} AS op, event_id,
         lower(split_part(actor_user_name, '@', 2)) AS own, {_PS} AS ps
  FROM events WHERE {WHERE}
),
r1 AS (
  SELECT source_id, time, person, op, event_id, own,
         {_p("name", "rulename", "identity")} AS rule,
         {_p("from", "fromaddresscontainswords")} AS sender,
         {_p("sentto")} AS sent_to,
         {_p("subjectcontainswords", "subjectorbodycontainswords", "bodycontainswords")}
           AS words,
         nullif(regexp_replace({_p("movetofolder", "copytofolder")}, '^[:\\\\/]+', ''), '')
           AS folder,
         lower(coalesce({_p("deletemessage", "softdeletemessage")}, '')) = 'true' AS deletes,
         lower(coalesce({_p("markasread")}, '')) = 'true' AS marks_read,
         lower(coalesce({_p("stopprocessingrules")}, '')) = 'true' AS stops,
         {
    _p(
        "forwardto",
        "redirectto",
        "forwardasattachmentto",
        "forwardingsmtpaddress",
        "forwardingaddress",
    )
} AS forward_to,
         lower(coalesce({_p("ruleactions")}, '')) AS outlook_actions
  FROM r0
),
r2 AS (
  SELECT *,
         list_filter(
           regexp_extract_all(lower(coalesce(forward_to, '')), '@([a-z0-9.-]+)', 1),
           d -> d <> own
         ) AS outside
  FROM r1
),
rules AS (
  SELECT source_id, time, person, op, rule, sender, sent_to, words, folder, stops, forward_to,
    event_id,
    CASE
      WHEN nullif(forward_to, '') IS NOT NULL
        OR regexp_matches(outlook_actions, 'forward|redirect') THEN 'forwarding'
      WHEN deletes OR regexp_matches(outlook_actions, 'delete') THEN 'deleting'
      WHEN list_contains({list(HIDDEN_FOLDERS)}, lower(folder))
        OR (marks_read AND folder IS NOT NULL)
        OR regexp_matches(outlook_actions, 'junk|rss feeds|conversation history|archive')
        THEN 'hiding'
      WHEN folder IS NOT NULL OR regexp_matches(outlook_actions, 'move') THEN 'organizing'
      ELSE 'other'
    END AS class,
    len(outside) > 0 AS external,
    CASE
      WHEN nullif(forward_to, '') IS NOT NULL
        THEN 'forward to ' || forward_to
      WHEN deletes THEN 'delete'
      WHEN folder IS NOT NULL
        THEN CASE WHEN marks_read THEN 'mark read, move to ' ELSE 'move to ' END || folder
      WHEN marks_read THEN 'mark read'
      ELSE nullif(outlook_actions, '')
    END AS action,
    regexp_matches(lower(coalesce(words, '') || ' ' || coalesce(rule, '')), '{MONEY_WORDS}')
      OR regexp_matches(lower(coalesce(sender, '')), '{SENSITIVE_SENDERS}') AS sensitive
  FROM r2
),
classed AS (
  SELECT *,
    class IN ('hiding', 'deleting') OR (class = 'forwarding' AND external) AS risky
  FROM rules
)"""  # noqa: S608  # fixed SQL text

RISK = "CASE WHEN risky AND sensitive THEN 'high' WHEN risky THEN 'medium' ELSE 'low' END"
# A burst: one person's rules with no gap over 24 hours between them ("created 62 rules
# Oct 29 to 30"). The page groups the list by it.
BURST_GAP_H = 24


def list_sql(cond: str | None = None) -> str:
    """Every rule in the page's window (`{from}`, `{to}`), risky first, with its burst;
    `cond` narrows it (the rows behind a count)."""
    where = f"WHERE {cond}\n" if cond else ""
    return (
        f"WITH {RULES_CTE.strip()},\n"  # noqa: S608  # fixed SQL text; cond is ours
        "g AS (\n"
        "  SELECT *, CASE WHEN time - lag(time) OVER (PARTITION BY person ORDER BY time)\n"
        f"    > INTERVAL {BURST_GAP_H} HOUR THEN 1 ELSE 0 END AS gap\n"
        "  FROM classed\n"
        "  WHERE time >= TIMESTAMPTZ '{from}' AND time < TIMESTAMPTZ '{to}'\n"
        "),\n"
        "w AS (\n"
        "  SELECT *, sum(gap) OVER (PARTITION BY person ORDER BY time) AS burst_no FROM g\n"
        ")\n"
        "SELECT time, person, op AS operation, rule, sender AS from_address, sent_to,"
        " words AS subject_words, action, folder, stops AS stop_processing,"
        f" class, external, risky, {RISK} AS severity,\n"
        "       person || '|' || burst_no AS burst, event_id\n"
        f"FROM w\n{where}"
        "ORDER BY risky DESC, time DESC"
    )


def counts_sql() -> str:
    """Risky rules now and before, and organizing rules now, from `$start`."""
    return (
        f"WITH {RULES_CTE.strip()}\n"  # fixed SQL text
        "SELECT count(*) FILTER (WHERE risky AND time >= $start),\n"
        "       count(*) FILTER (WHERE risky AND time < $start),\n"
        "       count(*) FILTER (WHERE class = 'organizing' AND time >= $start)\n"
        "FROM classed"
    )
