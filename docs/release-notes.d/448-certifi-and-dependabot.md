### Trusted certificate list updated (2026-11-08)

- The bundled list of trusted certificate authorities (`certifi`) moves to 2026.10.23, which drops a root whose revoked intermediates had compromised keys (PYSEC-2026-4320). Outbound HTTPS (feeds, connectors, alert targets, AI providers) no longer trusts it.
- The CI exception for that advisory is removed, and Dependabot now opens grouped security updates, still held to the 14-day minimum age.
- What you will notice: nothing visible.
- What changes for existing installs: update to pick up the new certificate list; nothing to configure.
