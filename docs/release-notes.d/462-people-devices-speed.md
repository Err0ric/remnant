### People & devices opens faster on large installs (2026-11-08)

- People & devices no longer reads the extra fields of every sign-in. Windows sign-ins carry about 1.5 KB of fields with no column of their own; two checks read them for every sign-in in the range: the test record check in who counts as a person (a test record names no one, and every row there names someone) and the Claude Code hook fields in the ranking (now read from hook rows alone).
- On a synthetic week of 1.9 million sign-ins and 5.7 million DNS queries, the page's server time went from about 7.9 s to 1.4 s, and its server CPU from about 15 s to 2.4 s. The ranking, scores, and Identities scoping are unchanged.
- The speed check can add the same real-shaped week to its lake (`--real-shape`, off by default).
- What you will notice: People & devices opens much faster on large installs.
- What changes for existing installs: nothing to do. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
