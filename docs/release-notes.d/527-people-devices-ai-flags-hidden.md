### People & devices hides a person's AI watch flags without View people in AI usage (2026-11-12)

- People & devices listed, next to each person's name, the AI watch flags on them (personal Claude account, unreviewed AI service, new MCP server, blocked or failed tool calls) and counted AI Watch alerts about them, for every viewer. That is AI usage by person, which **View people in AI usage** is meant to keep to the people an admin chose (D242, ADR-0029 G2; found by the 2026-11 audit).
- Without the permission, a person's row now carries no AI watch flags, counts no AI Watch alerts, and its score leaves both out. The AI watch flags column says "Hidden" for people. Machines and addresses keep their flags and alerts, as on the AI pages (machines, never names). The check is on the server (`GET /api/entities/risk`).
- Administrators and anyone with the permission see the page as before.
- Each load of the ranking is recorded as on the AI pages (ADR-0029 G3): `ai.view_people` (page `investigate.risk`) when it showed a person with an AI watch flag or an AI Watch alert, otherwise `ai.view`. This is one more audit entry per load, next to `investigate.risk`.
- What you will notice: without View people in AI usage, the AI watch flags column on People & devices says "Hidden" for people, and their scores no longer include AI watch flags or AI Watch alerts.
- What changes for existing installs: nothing to do. An admin can turn on View people in AI usage for someone on the Users page. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`).
