### Setup: a valid setup link works even when wrong ones reached the limit (2026-11-12)

- Wrong setup links are limited per address (5 in 5 minutes). Behind a reverse proxy without `trusted_proxies` every person has the proxy's address, so someone sending wrong links could keep the real first setup out. A valid, unexpired link now passes that limit (owner decision, D245 amended); wrong and expired links still count and are refused, and the link check is unchanged.
- `docs/install/tls.md` says to set `trusted_proxies` so the limits count each person's own address.
- What you will notice: nothing visible, unless your first setup was being blocked with "Too many failed attempts".
- What changes for existing installs: nothing. To go back: `update-systemd.sh --rollback` (see `docs/install/team-vm.md`, Rolling back).
