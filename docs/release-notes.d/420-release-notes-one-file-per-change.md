### Release notes and decisions: one file per change (2026-11-05)

- Each change now adds its own release note file (`docs/release-notes.d/`) and, for a decision, its own row file (`docs/decisions.d/`). `scripts/docs/assemble.py` writes them into this page and the SPEC decisions log, so changes no longer edit the same lines. The page reads as before.
- What changes for existing installs: nothing to do.
