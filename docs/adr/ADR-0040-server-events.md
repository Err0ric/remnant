# ADR-0040: The server's own security events in the lake, for detections

Status: **Accepted** 2026-10-30 (owner, 20:46): option A; all refusals now (ingest tokens, sign-ins including single sign-on refusals, API tokens), rate-capped; the detection ships **on**, other starter rules stay off. Recorded as SPEC D128. Item 6 of the owner's 19:11 list.

## Context

The OTLP receiver refuses a request with a missing, wrong, or revoked token and logs `otlp.refused` with the client address and the token id or prefix (built in D127). That line goes to the server's log (stderr, so journald or `docker logs`), not the lake. A detection for "10 or more refusals from one address in 10 minutes" needs the refusals somewhere a rule or a scheduled search can read, with source access, retention, and integrity like any other events. Today nothing in the server writes events about itself into the lake; the audit log is a separate table with no search.

## Options

| | Option | For | Against |
|---|---|---|---|
| A | **A built-in source, `server`**, written by the server through the same spool and writer as OTLP: refused ingest tokens (`otlp.refused`), refused sign-ins (`auth.login` failures and rate limits), and refused API tokens. A `server_events` template maps them to OCSF (Authentication 3002 for sign-ins and tokens, with `status_id = 2`, `src_endpoint_ip`, and the token id or user name). Admin-only by default like any new source (Q4). A starter Sigma rule, **Ingest token guessing** (10 or more refused ingest tokens from one address in 10 minutes), plus **Sign-in guessing** on the same events, shipped disabled with the starter rules | One place, one access model, the rule is visible and tunable, Search and the Dashboard can count them, and it covers the next refusal type for free | The server writes its own events: a small new path (bounded: at most a few hundred rows a minute, dropped and counted past that, so a flood cannot fill the disk) |
| B | An **in-server counter** that raises an alert item when one address passes the threshold | Small; no lake path | Not visible as a rule, not searchable, a second detection mechanism beside Sigma |
| C | **Document** reading the server's own log (journald to a file source) with a template and the rule | No server change | Every install has to set it up; Docker and systemd differ; easy to miss |

## Recommendation

**A.** It keeps one detection mechanism (Sigma rules and schedules on events), the rule is something an admin can see and tune, and the next refusal (API tokens, MCP tokens) needs only a mapping. Rate-capped so the server cannot fill its own lake.

## Owner answers (2026-10-30)

1. A.
2. All refusals now: ingest tokens, sign-ins (wrong password, the sign-in rate limit, single sign-on refusals), and API tokens.
3. On by default: it protects this server and only counts refusals.

## As built

- `app/ingest/server_events.py` writes each refusal to the OTLP spool for the built-in `server_events` source (created on first use, admin-only like any new source), at most 300 a minute; past that they are counted on the next event. Never a password or a token: the token's id when it is one of ours, else its first 8 characters.
- The `server_events` template maps them to OCSF Authentication with `status_id = 2`, the address, the user name tried, and the reason.
- Sigma correlation rules (a count over time) are not supported yet, so the detection is a built-in check (`app/search/refusals.py`), run every minute: one High alert item per address per hour when an address has 10 or more refusals in 10 minutes. It is shown on Alerts > Rules with Turn off and the threshold (3 to 1000), audited `detect.refusals`. When correlation rules arrive it can move to a rule file.

## Questions for the owner (answered above)

1. A, B, or C?
2. With A: include refused sign-ins and API tokens now, or only ingest tokens first?
3. With A: should the starter rule ship enabled (it only counts refusals, which are rare and never content), or disabled like the other starter rules?

## ATLAS and ATT&CK

- T1110.001 Brute Force: Password Guessing, and T1110.003 Password Spraying, against ingest and API tokens and sign-ins.
- No AI-facing change: the events hold no prompt or model content; Ask reads them like any source the viewer may read.
