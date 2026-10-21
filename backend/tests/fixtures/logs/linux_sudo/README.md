# linux_sudo fixtures

| | |
|---|---|
| Source product | sudo 1.9.15 with pam_unix |
| Collector shape | rsyslog 8.2312, RFC 3164 with PRI (authpriv) |
| Generator | `scripts/fixtures/starter_pack.py linux_sudo` (seed 21) |
| Values | Synthetic users and hosts |

Command runs with and without a TTY, incorrect password attempts (1 to 3), not in sudoers, PAM sessions opened and closed, and one "unable to resolve host" line that keeps only its envelope. Pathological: a 9 KB user name, 5,000 separators, and a huge attempt count.
