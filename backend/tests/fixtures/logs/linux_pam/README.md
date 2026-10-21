# linux_pam fixtures

| | |
|---|---|
| Source product | Linux-PAM 1.5 (pam_unix, pam_faillock) with util-linux su 2.39, cron, login |
| Collector shape | rsyslog 8.2312, RFC 3164 with PRI (authpriv) |
| Generator | `scripts/fixtures/starter_pack.py linux_pam` (seed 22) |
| Values | Synthetic users and hosts |

su authentication failures, login and cron sessions, password changes, faillock lockouts, su success and failure, and one su audit line the template does not model. Pathological: 3,000 key=value pairs after an auth failure, 5,000 open parentheses, and a 9 KB target name.
