### A time without a zone means UTC everywhere (2026-11-14)

- An API or CLI request whose start, end, or other time has no zone (`2026-11-14T08:00:00`) is now read as UTC in every step: which days of data are read, the row filter, the rollups AI usage and Microsoft 365 read, and the Proxmox guest lookup. Before, on a server whose own zone was not UTC, such a window near midnight could leave out the events of a day or read a day it did not need.
- The audit log filters, a rule run, and a saved search's time parameters now read such a time as UTC too, where they used to refuse it.
- What you will notice: nothing in the web pages, which always send times with a zone; API scripts that send times without one now get the days they asked for.
- What changes for existing installs: nothing to do.
