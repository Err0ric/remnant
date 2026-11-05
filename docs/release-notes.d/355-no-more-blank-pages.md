### No more blank pages (2026-11-02)

- If a page fails to show, you now see "Something went wrong on this page" with a **Reload** button and an error id instead of a blank page. One failing Dashboard panel shows an error card and the rest of the page still loads.
- After an update, a tab left open on the old version reloads itself once when it needs a page file the new version no longer has. It never reloads in a loop.
- Page and panel failures are reported to the server: administrators see them on **Health** under "Browser errors, last 24 hours", and they are in the server log as `client.error`. Reports carry the error kind, a short message with values removed, the page path, and the build, never log content.
- What changes for existing installs: nothing to do. Tabs opened before this update may need one manual refresh.
