### Ask's time limit in Settings > AI providers (2026-11-17)

- An Admin can set Ask's time limit, the longest one Ask model call may take, in Settings > AI providers (Ask time limit), from 5 to 3600 seconds. The help says: "CPU-only local models may need 240 s or more."
- A saved value takes the place of `ask.model_timeout_s` from the config, and "Use the configured value" clears it; the page says whether the limit in force is saved there or from the install's configuration. Each change is in the audit log as "Changed the Ask time limit", with the old and new value.
- The live search time limit in Settings > About and licenses is drawn by the same control; it looks and works as before.
- What you will notice: Settings > AI providers has an Ask time limit box an Admin can change.
- What changes for existing installs: the default stays 90 seconds, or what `ask.model_timeout_s` says, until an Admin saves a value. CPU-only local models may need 240 s or more. To go back, click "Use the configured value"; rolling back as in `docs/install/` (`update-systemd.sh --rollback`) also works, and the older version ignores the saved value.
