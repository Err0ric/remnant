### AI Watch and Dashboard sections no longer fail during compaction (2026-11-03)

- Compaction, which merges small log files every hour, now keeps the files it replaces for 30 minutes before deleting them. A search or background check that had already started reading them finishes normally instead of failing with "Cannot open file". This was the cause of AI Watch failing every hour on busy sources, and of Dashboard sections such as Attacks and access failing to load.
- A read no longer counts events twice for a moment while a merge is finishing.
- The integrity ledger records each removal when the file is actually deleted.
- What changes for existing installs: nothing to do. Day folders get a small `_retired.json` file while replaced files wait to be deleted.
