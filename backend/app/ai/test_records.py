"""Test records are not use (owner, 2026-11-04).

The installer's doctor and Send a test record post one synthetic SessionStart marked
`test_record=true`, with no person and no machine. Every count of Claude Code use (the
ai_agents library pack, AI usage, Agents, Sessions, and AI watch alerts) leaves them out.
The mark is set by the sender, so a record counts as a test only when it is marked and
names no person and no machine: a real client cannot hide its own use by setting it.
Health and a session's own drill still see them (the doctor's check is that it arrived).
"""

from __future__ import annotations

TEST_RECORD = (
    "(coalesce(json_extract_string(unmapped, '$.attr.test_record'), '') = 'true'"
    " AND nullif(trim(actor_user_name), '') IS NULL"
    " AND nullif(trim(device_hostname), '') IS NULL)"
)
NOT_TEST = f"NOT {TEST_RECORD}"
# Hook records that are use: the plugin's template, test records left out.
HOOKS = f"(template_id = 'claude_hooks' AND {NOT_TEST})"
