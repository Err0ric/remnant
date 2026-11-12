### AI usage counts Windows DNS lookups and each hook record once (2026-11-08)

- Windows DNS, Unbound, and PowerDNS put the looked-up name in `message`, which AI usage did not read, so their lookups of AI services were missed. AI usage, AI Watch, and the AI parts of People & devices and the top bar lookup now read it on DNS events. A name kept in the extra fields still comes first.
- Finding AI service lookups no longer reads the extra fields of sign-ins (Windows sign-ins carry about 1.5 KB each), and parses those fields only when they hold a host. On a synthetic day of 1.36 million sign-ins and 814,500 Windows DNS queries, today's AI check went from about 2.7 s to 1.6 s while now reading the DNS lookups.
- AI usage, People: a hook record the plugin sent twice counts once, as on Agents and Sessions. People seen only through the hooks plugin show for Last 7 days with or without the AI rollup built (tests added).
- What you will notice: Windows DNS lookups of AI services now count in AI usage; tool call counts in People no longer double for a record the plugin resent.
- What changes for existing installs: nothing to do. Days the AI rollup already built keep their counts until those days change; new days and today include Windows DNS lookups. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
