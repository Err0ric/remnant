### Hooks plugin diagnostics (2026-11-02)

- Plugin version 2.2.0 leaves a status file after every run (last run, event, sent or queued or skipped and why, HTTP status, queue depth). It holds no token and no content.
- `install-local.sh --doctor` and `install-local.ps1 -Doctor` check a machine and print a pass or fail list: config, certificate, server, token (with one test record), whether Claude lists the plugin, and the hook's last status.
- The hooks guide now says which install paths are known to fire hooks and which are untested, and has a troubleshooting table for the status file.
- What changes for existing installs: download the plugin again and reinstall it to get 2.2.0.
