# linux_systemd fixtures

| | |
|---|---|
| Source product | systemd 252 to 255 (Debian 12, Ubuntu 24.04) |
| Collector shape | rsyslog 8.2312 from journald forwarding, RFC 3164 with PRI |
| Generator | `scripts/fixtures/starter_pack.py linux_systemd` (seed 30) |
| Values | Invented unit and host names |

Units started and stopped (249+ "unit - description" form), main process exits with SUCCESS and FAILURE, "Failed with result", "Deactivated successfully", user session scopes, and targets. Pathological: a 9 KB unit name, 5,000 slashes in an exit status, and 1,200 repeated "Started".
