### Log rotation: a rotated file is watched for 30 seconds more (2026-11-13)

- D252 (ADR-0051 row 3). After a rotation, a program often keeps writing to the old file for a moment, until it is told to reopen its log. The server now keeps the renamed file open for 30 seconds after it has read it to its end, and reads what is still written to it in that time. Before, it closed the file as soon as it had read it to its end, so those lines were lost on a source that watches a single file.
- A last line without a line ending in the renamed file is stored when the file is closed, not at the moment of the rotation. A line the program finishes within those 30 seconds is stored whole.
- The file is closed 5 minutes after the rotation at the latest, as before.
- What you will notice: nothing in the app. The last lines before a rotation arrive up to 30 seconds later when they had no line ending yet.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
