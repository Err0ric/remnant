# Anthropic: API usage, cost, Claude Code, and audit activity

The Anthropic source reads your organization's reports from Anthropic's admin APIs every 5 minutes: API token usage and cost, Claude Code use per person, claude.ai use per person (Enterprise), and the audit activity feed. It never reads conversations, files, or projects. Design: [ADR-0015](../adr/ADR-0015-ai-usage-visibility.md) row 10.

This complements Claude Code telemetry ([claude-code-telemetry.md](claude-code-telemetry.md)), which comes from the endpoints in real time. The Anthropic source is the organization's billing and audit view, a day behind for the per-person reports.

| Feed | What is in it | Key | Arrives |
|---|---|---|---|
| `usage` | Tokens per hour by model, workspace, and API key | Admin | Each finished hour |
| `cost` | Cost per day by workspace and description | Admin | Each finished day |
| `claude_code` | Per person per day: sessions, lines added and removed, commits, PRs, tokens, estimated cost | Admin or Analytics | 2 hours after the day ends (UTC) |
| `analytics_users` | claude.ai per person per day: conversations, messages, Claude Code sessions | Analytics (Enterprise) | From 14:00 UTC the next day |
| `compliance_activities` | Audit events: API keys created and deleted, members invited and removed, settings changed, with who and from which IP | Compliance (Enterprise) or Admin | Every 5 minutes |

Which feeds your organization can read depends on its plan. **Test connection** shows which work with your key, before you save.

## 1. Create a key

A member with the organization **admin** role creates it in the [Anthropic Console](https://console.anthropic.com) under the organization settings. Admin API keys start with `sk-ant-admin`. For the Analytics and Compliance keys, follow Anthropic's current instructions for your plan (Claude for Enterprise documentation).

Use a key made for this source only, so revoking it affects nothing else. Admin keys can also manage your organization (members, workspaces, other keys); if your plan offers a read-only Analytics or Compliance key for the feeds you need, prefer it.

## 2. Add the source

**Sources > Add source**, then **Reads from: Anthropic**.

| Field | Value |
|---|---|
| Source ID | For example `anthropic_org` |
| Parser | Set for you: **Anthropic usage, cost, and audit** |
| Key type, API key | From step 1 |
| Feeds | Tick the ones your key can read |
| On first run, read back | Days of history to read the first time, up to 31 |

Select **Test connection**. **Works** next to each feed means save. A 401 or 403 means the key cannot read that feed; a 404 means the feed is not offered to your organization or plan. Untick feeds that do not work.

The server needs outbound HTTPS to `api.anthropic.com`, directly or through a proxy ([proxy.md](proxy.md)).

## What lands

Every record is one JSON line, `{"feed": "anthropic.<feed>", ...}`, holding Anthropic's object as returned. Columns:

| Column | Value |
|---|---|
| `message` | The feed, for example `anthropic.claude_code`, or the activity type for audit events (`api_key_created`) |
| `actor_user_name` | The person's email, or the API key id for `usage` |
| `src_endpoint_ip` | Audit events: where the action came from |
| `time` | The start of the hour or day, or the audit event's time |
| `unmapped` | Everything else: tokens, cost, model, workspace, terminal, lines of code |

Example searches:

```sql
-- Claude Code use per person over the last 30 days
SELECT actor_user_name,
       sum(CAST(json_extract(unmapped, '$.core_metrics.num_sessions') AS INT)) AS sessions
FROM events
WHERE message = 'anthropic.claude_code' AND time > now() - INTERVAL 30 DAY
GROUP BY 1 ORDER BY 2 DESC;

-- New API keys and member changes
SELECT time, actor_user_name, message, src_endpoint_ip
FROM events
WHERE template_id = 'anthropic_reports' AND message NOT LIKE 'anthropic.%'
ORDER BY time DESC;
```

## Day to day

- **Replacing the key:** **Sources > (the source) > Replace credentials**. Reading continues from where it was.
- **Rate limits:** when Anthropic asks the server to slow down, the source waits as asked and the Sources page shows when it tries next.
- **Classification:** starts `local_only` like every source.
- **Removing it:** delete the source, then revoke the key in the Console.
