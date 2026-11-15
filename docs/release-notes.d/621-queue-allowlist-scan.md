### The merge queue checks each pull request for real-looking names (2026-11-14)

- The merge queue now runs the allowlist scan (the synthetic-only rule) on the files a pull request adds or changes, renamed files under their new names, leaving out what is never published. A pull request that changes the scan's own rules (the export rules, the allowlist, the reviewed binaries, or the scanner) gets the whole tree scanned instead. A real-looking domain, address, or file name stops the queue at merge instead of at publish, and so does a scan that could not run. The publish step still scans the whole tree.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do.
