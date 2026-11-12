### Development roles kept out of the public repository (2026-11-10)

- CLAUDE.md section 10 imports the development roles and owner checkpoints from `.claude/factory.md` (D238). That file, the development agents and commands (`.claude/`), and design and bug proposals (`docs/proposals/`) are left out of the public repository.
- The publish script now stops if `.claude/` or `docs/proposals/` would be published, so a missing `.gitattributes` line cannot leak them.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Development files only; nothing in the app, data, settings, or update steps changes.
