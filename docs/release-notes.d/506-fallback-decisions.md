### One message each way for a missing parser; reparse count in the integrity report (2026-11-11)

- A source storing events without its parser no longer also sends the general "Detection stopped" and "Detection running again" messages after 15 minutes. Its own two messages ("Source without its parser" and "Source parser back") cover it, so one outage sends two messages instead of four (D239).
- The integrity report now shows how many files and events were reparsed in its period (D240).
- What you will notice: fewer duplicate alert messages when a parser goes missing; a reparse count in the integrity report.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
