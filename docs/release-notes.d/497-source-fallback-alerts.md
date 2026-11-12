### A source without its parser says so on Health and to alert targets (2026-11-10)

- When a source keeps storing events without its parser (its template is not available), Health and Sources now say which source and which template, and that rules and searches using the template's fields miss those events until they are reparsed. Analysts who read the source see the same words, not "cannot be read right now".
- Every alert target gets one message when it starts ("Source without its parser") and one when the template loads again ("Source parser back"), with how many events were stored without it. Nothing repeats while it lasts, also across restarts. Both are in the audit log (ADR-0050 rows 4 to 6).
- If the outage lasts more than 15 minutes, the general "Detection stopped" and "Detection running again" messages also go out, so four messages in all; whether to leave this case out of them is with the owner.
- What you will notice: a clearer Health message for such a source, and alert messages when it starts and ends (two, or four past 15 minutes).
- What changes for existing installs: nothing to do. The update adds one small table to the settings database. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); the older release ignores the table.
