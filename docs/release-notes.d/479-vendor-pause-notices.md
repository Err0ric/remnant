### Vendor alert pause messages (2026-11-10)

- When a vendor alert source goes over 100 new alerts an hour, its alert targets now get a short message right away saying alert creation is paused and that High and Critical alerts still raise. The summary with held counts still comes when the pause ends.
- If the source has no alert targets chosen, both messages go to every alert target.
- What you will notice: a "Vendor alerts paused" message when a pause starts and a "Vendor alerts resumed" message when it ends.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`); no data or settings change.
