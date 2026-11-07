### Import SigmaHQ core rules (2026-11-07)

- Detection rules has an **Import SigmaHQ core rules** button for administrators. It downloads the SigmaHQ core rule package for the release pinned in the app (`r2026-07-01`) from GitHub, only when you click, and imports it only if its SHA-256 matches. Without internet access, upload the same `sigma_core.zip` instead.
- Imported rules start disabled and show up under **Recommended rules for your sources** when one of your sources would run them. Importing the same release again adds nothing and keeps rules you enabled.
- A broken rule file in a package or folder is skipped with its reason instead of stopping the import; the result counts rules imported, skipped, and not compiling.
- What changes for existing installs: nothing until an administrator clicks the button or uploads a package; no rules are fetched on start-up or on a schedule.
