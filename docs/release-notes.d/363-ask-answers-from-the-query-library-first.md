### Ask answers from the query library first (2026-11-02)

- Ask now reads the time ("today", "yesterday", "this week", "last 6 hours") and the people, addresses, and machines in your question itself, then picks a shipped library query when one fits and runs it with those as filters. The model only decides which library query fits; it writes SQL only when none does. **How I got this** names the library query, the filters, and the time.
- Questions that ask for general advice rather than your data are recognized as such; for now Ask offers **Check your data instead**. General guidance answers come in a later update.
- With no AI provider set up, Ask still suggests up to three library queries that match your words.
- Every library query now carries example questions (`ask:` in the pack files).
- What changes for existing installs: nothing to do.
