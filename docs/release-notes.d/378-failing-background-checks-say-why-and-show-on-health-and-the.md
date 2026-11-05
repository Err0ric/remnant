### Failing background checks say why, and show on Health and the Dashboard (2026-11-03)

- When AI Watch, a page refresh, or another background check fails, the server log now names the database's own error and its message (values from your logs are cut out), not only the error class.
- AI Watch runs its three steps separately, so one failing step no longer stops the others.
- **Health** lists checks that are failing, since when, how many runs failed, and why, with **Check AI Watch now** to run every step at once. The Dashboard's **AI Watch** panel says when its checks are failing and that alerts and review items may be behind.
- A page that read files during a rollup update is read again once instead of failing.
- What changes for existing installs: nothing to do. After updating, open Health and choose Check AI Watch now to see why it was failing.
