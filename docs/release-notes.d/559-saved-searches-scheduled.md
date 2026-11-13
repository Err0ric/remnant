### Design: Saved searches shows what is scheduled (2026-11-13)

- Console redesign, build row 8 (ADR-0052 section 3.3). Saved searches is a tab of Logs (since the new rail) and its table has a Scheduled column: a search that runs on a schedule shows when ("Daily at 07:00"), and that is a link to the schedule on Alerts > Schedules, which opens with that schedule marked. A search with no schedule says No.
- Only schedules you can see are listed, the same ones Alerts > Schedules shows you.
- The old address `/saved` still opens the tab.
- What you will notice: a Scheduled column on Saved searches.
- What changes for existing installs: nothing to do.
