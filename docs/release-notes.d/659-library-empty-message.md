### Who had this address: says when there is no lease (2026-11-17)

- When "Who had this address" (`who_had_ip`) finds nothing, Logs and Ask AI say "No DHCP lease for this address in the range. It may be a static address." in place of "Try a wider time range or remove a source filter."
- In Logs this holds while the query opened from Library is unchanged or only its address is; after any other edit the usual text shows.
- A query library pack may give any query its own words for no rows, with the new optional field `empty:` (plain text, at most 160 characters). The Palo Alto pack is now version 1.2.0.
- What you will notice: an address lookup that finds no lease says so, and that the address may be static.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`), but first remove `empty:` from your own packs (the folder `paths.library` names): the older version refuses a pack that has it, and leaves that pack's queries out until it is removed. The packs shipped with the product need nothing.
