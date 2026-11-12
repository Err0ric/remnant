### Server logs follow the current error stream (2026-11-11)

- The server's log lines are written to the error stream as it is at each write, not as it was when logging started. A server is unchanged; tests no longer fail now and then with "I/O operation on closed file" when one test's captured output was closed before another logged.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
