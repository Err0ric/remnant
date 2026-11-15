### Quiet is normal now also holds the quiet alert (2026-11-14)

- On a source marked "Quiet is normal for up to" some days, its quiet alert waits for those days: no alert and no message while the silence is inside them.
- Once the days pass, the alert fires once, as it would have, with when the silence started. Taking the mark off checks the alert again at the next check, within 30 seconds.
- An alert that is already firing stays until events resume or someone closes it. Errors and refused records are raised as before.
- What you will notice: a marked source that is quiet for a few hours no longer sends a "stopped sending" alert; the setting says its quiet alert is held for these days.
- What changes for existing installs: sources already marked Quiet is normal now also have their quiet alert held for their days; nothing changes for unmarked sources. Going back to the previous version sends quiet alerts as before (`docs/install/`, `update-systemd.sh --rollback`).
