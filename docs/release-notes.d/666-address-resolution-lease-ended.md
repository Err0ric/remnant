### Address resolution reads DHCP lease ended lines (2026-11-17)

- Where an address is matched to a machine (People & devices, the person and address pages, AI usage), a DHCP lease now ends at its "lease ended" line instead of running on until the next lease of the address or 24 hours.
- A lease that started before the time range and ended inside it now names its machine from the end line, so the first hours of a range are matched too.
- An end line logged after another machine took the address no longer cuts that machine's lease short.
- An hour is matched to the same machine whatever time range the page shows, and the address lookup (who had it at a time) reads the lines up to 24 hours after that time too, so it sees the end line of a lease that was still running.
- These are the same rules as the library query "Who had this address", and both read a DHCP line the same way, so the two name the same machine for an address at a time.
- What you will notice: an address is matched to the machine that held it at the time, also in the first hours of a range and after a lease ended.
- What changes for existing installs: nothing to do. Lines already stored are read with the new rule on the next page load; AI usage reads days it summarized before the update with start lines only, and days from the update on with both. To go back, install the previous version as in `docs/install/` (`update-systemd.sh --rollback`).
