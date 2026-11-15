### Person page: the name is hidden in the title, Accounts, and Timeline without View people in AI usage (2026-11-14)

- D242 (owner, 2026-11-14). For someone without View people in AI usage, a person's page is titled "Name hidden" (still marked Person), and the Accounts box and the Timeline say how many names are hidden ("2 names hidden") in place of the names. The Entity card in How it connects reads "Name hidden", and an empty How it connects says "this person".
- The names counted as the person are not sent to the browser for those viewers: `GET /api/people/{person}/record` and `GET /api/people/{person}/timeline` send `forms` empty with the count in `forms_hidden`, and the timeline's "Possibly the same person" list empty.
- Opening Logs from the page says "From this person > ..." in place of the name.
- In "What it did", the "by <name>" label is left out for those viewers; the example log line under it is log data and is unchanged.
- The notice above the summary now reads "Names are hidden: this person's name and AI activity are not shown." and says an admin can turn on the permission.
- The page address still names the person, and the identity rows on the page (sign-ins, alerts, devices, addresses, and the Logs queries) still name the account, since that is log data the viewer may read in Logs.
- What you will notice: without View people in AI usage, a person's page shows "Name hidden" as its title and a count of hidden names in Accounts and the Timeline; with the permission, nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
