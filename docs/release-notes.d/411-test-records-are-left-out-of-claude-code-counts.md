### Test records are left out of Claude Code counts (2026-11-04)

- The installer's doctor check and **Send a test record** no longer count as a person with a blank name. They are left out of the AI agents library (for example "Who uses Claude Code"), AI usage, Agents, Sessions, and AI watch alerts. Health still shows that they arrived.
- A record counts as a test only when it is marked as one and names no person and no machine, so a real session cannot be hidden by marking it.
- What changes for existing installs: nothing to do; test records already stored drop out of the counts on the next page load.
