# windows_winlogbeat fixtures

| | |
|---|---|
| Source product | Windows Security and System event logs (Windows Server 2022 shape) |
| Collector shape | Winlogbeat 7.17 and 8.15 JSON documents as written by the file output (alternating); 8.x lines carry `event.outcome`, 7.x lines only `winlog.keywords` |
| Generator | `scripts/fixtures/starter_pack.py windows_winlogbeat` (seed 42) |
| Values | Synthetic CORP domain, invented users and hosts, RFC 1918 and RFC 5737 addresses |

Same event mix as `windows_nxlog_json`, generated from the same canonical events so all Windows templates are held to the same OCSF values. `winlog.event_id` alternates between string and number. Pathological lines add a non-object `event_data` and null and numeric values in place of strings.
