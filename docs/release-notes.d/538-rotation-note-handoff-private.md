### Docs: rotate with create, not copytruncate; rotation ADR draft; the session handoff is not published (2026-11-12)

- `docs/ingest/README.md` and the rsyslog guide now say to rotate log files by rename (logrotate `create`), not `copytruncate`, to keep rotated copies out of a source's file pattern, and name the gap that remains (a line written in the last seconds before a rename can be missed). The rsyslog guide no longer says both styles are handled. Found by the 2026-11 audit (H5).
- `docs/adr/ADR-0051-file-rotation.md` is a draft for the owner's review: one read position per file, not per path. Nothing in it is built.
- Development only: `docs/handoff.md` (open work and owner questions) is left out of the published tree, and `publish.sh` stops if it would be published. The install guide `docs/install/handoff.md` is unaffected.
- What you will notice: nothing visible in the app. If your logrotate rule uses `copytruncate`, change it to `create` as the guide shows.
- What changes for existing installs: nothing.
