### Design: Microsoft 365 is three views of Logs (2026-11-13)

- Console redesign, build row 9 (ADR-0052 section 3.3; owner, 2026-11-13). Microsoft 365 has no area of its own. Logs has a Views menu on every one of its tabs, with Microsoft 365 sign-ins, Microsoft 365 mail, and Microsoft 365 admin. Each view shows the lists the server builds and runs on the sources you can read, so they need no SQL access and show no editor: everyone who could open Microsoft 365 before can open the views.
- Nothing was dropped. The charts and lists of the old Overview (sign-in outcomes, failure reasons, sign-ins outside approved countries, apps signed in to) are at the top of the Sign-ins view. The app consents and app registrations lists of the old Apps tab are at the foot of the Admin view; the register of apps is AI usage > Inventory with Type set to Microsoft 365 apps.
- Old addresses still open: `/m365` and `/m365/sign-ins` open the Sign-ins view, `/m365/mail` and `/m365/admin` their views, and `/m365/apps` the Inventory on Microsoft 365 apps. The time window you chose is kept.
- Without a Microsoft 365 source a view says so, with Add a source.
- The views keep their 24 hours, 7 days, 30 days window for now.
- What you will notice: Microsoft 365 pages open under Logs, from a Views menu at the top right.
- What changes for existing installs: nothing to do. Bookmarks and links in alert messages keep working.
