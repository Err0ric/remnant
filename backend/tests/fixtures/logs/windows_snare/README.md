# windows_snare fixtures

| | |
|---|---|
| Source product | Windows Security and System event logs (Windows Server 2022 shape) |
| Collector shape | Snare for Windows v5 tab-delimited MSWinEventLog format, per the vendor's Windows Event Output Format appendix: two in three lines over syslog with a BSD header, one in three as file lines that start with the hostname |
| Generator | `scripts/fixtures/starter_pack.py windows_snare` (seed 43) |
| Values | Synthetic CORP domain, invented users and hosts, RFC 1918 and RFC 5737 addresses |

The Snare user column is `N/A` (as on current Windows), so users, addresses, and process names are read from the expanded message, which Snare flattens to one line. 4624 includes `Network Account Name: -` to prove it is not taken as the account logging on. The 4768 message gives `Client Address`, which is not mapped, so those lines have no source address. Pathological: a short record, 3,000 empty fields, 3,000 `Account Name:` labels with a bad date, and an oversized port.
