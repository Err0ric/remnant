### People and devices loads faster (2026-11-07)

- People and devices loads faster. The signals behind the ranking no longer test every event's address in Python: events are counted per user, address, and host in one pass, the signals are read only from sign-ins, hook events, and consents, and "internal" is decided in SQL once per distinct address of a failed sign-in. Rankings, scores, and their order are unchanged. On a 2 vCPU test server with 30 days and 7.3 million events (DNS, firewall traffic with probes from many outside addresses, sign-ins with a password spray, Claude Code hooks), median of 3 loads:

  | Server-Timing part | Before (ms) | After (ms) |
  |---|---:|---:|
  | signals_seen | 18,496 | 1,755 |
  | signals_mail_rules | 34 | 28 |
  | signals_new_mcp | 68 | 68 |
  | signals_unreviewed_ai | 493 | 502 |
  | people_split | 327 | 371 |
  | people_attackers | 128 | 138 |
  | scoring | 5 | 4 |
  | audit | 4 | 4 |
  | db | 19,374 | 2,636 |
  | app | 570 | 65 |
  | total | 19,944 | 2,930 |

- What changes for existing installs: nothing to do; the page reads the same data and the Internal networks list in Settings > Enrichment, only faster.
