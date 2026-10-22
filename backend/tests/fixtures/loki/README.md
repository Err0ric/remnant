# Loki stream fixtures

| | |
|---|---|
| Source product | Grafana Loki fed by a syslog receiver that strips the header into labels (`hostname`, `app_name`, `proc_id`, `severity`, `facility`), as Grafana Alloy and Promtail syslog receivers do |
| Values | Synthetic. RFC 5737 addresses, invented host and user names |
| Used by | `tests/integration/test_loki_source.py`, `tests/unit/test_labels.py` |

`streams.json`: each entry is one stream's labels and its line, plus what the row should
hold after Automatic parsing.
