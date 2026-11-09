### Health and the Dashboard agree on how many sources are healthy (2026-11-08)

- The Sources tile on Health and the Sources line at the bottom of the Dashboard now read one count, worked out once on the server. Before, Health could say "4 of 6 healthy" with two quiet sources while the Dashboard said "6 of 6 flowing, no gaps".
- Both say it in the same words, for example "4 of 6 healthy, 2 quiet: win_dc 2 d, vpn 6 h, no gaps in 24 hours". The count is the one Health already showed: a quiet source (nothing in 24 hours, a quiet alert firing, or an open gap alert) or one with a gap in the last 24 hours is not healthy, and a paused source counts in the total but is never healthy. The Needs you banner is unchanged.
- The built-in source of refused sign-ins and tokens (`server_events`) is expected to be quiet: it is never called quiet and never named as the longest wait. GET /api/sources marks it with `built_in` and `events_on_failure`; GET /api/overview adds a `condition` per source and a `source_summary`.
- What you will notice: the Dashboard's Sources line now says "N of M healthy" and names quiet sources, matching Health.
- What changes for existing installs: nothing to do. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
