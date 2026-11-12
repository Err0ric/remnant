### The start page is always the Dashboard, and the alerts note no longer counts what you can't read (2026-11-12)

- Opening the address of the app, or the product mark, now always opens the Dashboard, also when it has no panels yet (D243). Before, it opened Health when the Dashboard had no panel.
- When a source is not healthy or has a gap open, a one-line Health banner at the top of the Dashboard says so in the same words as the Sources line at the bottom, with Open Health.
- When an open alert is in a source you can't read, the Alerts summary and the Dashboard's Needs you banner say "Some alerts are in sources you can't read. Ask an admin for access." instead of how many there are. The alert API answers `restricted` as true or false, no longer a count. Admins read every source, so they never see the note.
- While the Health banner shows, the Sources line at the bottom of the Dashboard is hidden, so the problem is said once; the banner links to the gap alert when there is one, otherwise to Health. When every source is healthy the banner is gone and the bottom line shows as before (owner, 2026-11-12).
- What you will notice: the start page is always the Dashboard, with a banner when something needs attention on Health, and the alerts note no longer says how many alerts are in sources you can't read.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`): the older version opens Health again when the Dashboard has no panel and shows the count.
