# Mixed syslog stream

Synthetic. One file holding lines from several products, as a host's `syslog` file or a Loki
selector such as `{job="syslog"}` returns them. Built from the first lines of each starter
template's `sample.log` plus three lines no template claims (a cron job, an unknown daemon,
and a line with no syslog header). `expected_templates.txt` lists, line by line, the parser the
Automatic parser (ADR-0012) must choose. Collector: rsyslog-style RFC 3164 and RFC 5424 lines.
