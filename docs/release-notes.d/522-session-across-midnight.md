### Tests: a Claude Code session across midnight UTC counts once (2026-11-11)

- A session from 23:50 to 00:10 UTC (4 PM in UTC-8) was checked on every page that counts sessions: AI usage People and MCP servers, Agents Sessions, Accounts, and Overview, the person page's AI activity and timeline, with the AI rollup built or not, ending today or on closed days, over the last 7 days; AI usage People also for ranges that start or end at midnight. Each counts it once; sessions are counted from the events, never added up per day.
- The two sessions a test saw at 23:56 UTC came from the test's own helper, which named each session after the day of the month, so records either side of midnight had two session ids. The helper now uses one session id, and the new test keeps every page to one.
- What you will notice: nothing visible; a session across midnight already counted once.
- What changes for existing installs: nothing to do; tests only, the app and the AI rollup are unchanged and nothing rebuilds. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`).
