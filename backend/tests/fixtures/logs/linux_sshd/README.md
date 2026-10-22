# linux_sshd fixtures

| | |
|---|---|
| Source product | OpenSSH 9.6p1 server (`sshd`) with PAM |
| Collector shape | rsyslog 8.2312 forwarding, RFC 3164 with PRI (`<38>`) and some RFC 5424 lines |
| Generator | `scripts/fixtures/linux_sshd.py` (deterministic, seed 11) |
| Values | Synthetic: invented host and user names, RFC 1918 internal and RFC 5737 external addresses |

- `sample.log`: 66 lines. Accepted publickey, failed password, invalid user, connection closed `[preauth]`, PAM session opened and closed, disconnects, plus one timeout and one listener line the template does not map to a login.
- `expected.jsonl`: the parsed values for the first 10 lines, written by the generator from what it put in each line (not from the template).
- `pathological.log`: empty and junk lines, a 9 KB user name, an out-of-range port, a backtracking bait, control characters, a relay-wrapped header, and a headerless continuation line.

The last three lines of `sample.log` were added by hand for OpenSSH 9.8 and later, which logs as `sshd-session`.
