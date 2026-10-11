# windows_nxlog_json fixtures

| | |
|---|---|
| Source product | Windows Security and System event logs (Windows Server 2022 shape) |
| Collector shape | NXLog Community Edition 3.2, `im_msvistalog` with `to_json()`; one in three lines forwarded by `om_tcp` with a BSD syslog header |
| Generator | `scripts/fixtures/starter_pack.py windows_nxlog_json` (seed 41) |
| Values | Synthetic CORP domain, invented users and hosts, RFC 1918 and RFC 5737 addresses |

Events: 4624, 4625, 4634, 4688, 4720, 4732, 4740, 4768, 4776, 5156, 5157 (inbound and outbound), and System 7036 (not in the map, so a Base Event). EventTime alternates between the classic `YYYY-MM-DD hh:mm:ss` form and ISO 8601 with an offset. Class, activity, and status come from `templates/starter/maps/windows_eventid.yaml`. Pathological: 9,000 open braces, a string EventID with no data, nested and list values where strings belong, NaN-sized numbers and an unparseable time, a lone surrogate, a 30 KB message, and a syslog line without JSON.
