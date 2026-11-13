### Design: Health has three tabs; Backups, Page rollups, and Speed are in Settings (2026-11-13)

- Console redesign, build row 12 (ADR-0052 section 3.3; owner, 2026-11-13). Health has Sources, Collectors, and Delivery. Enrichment feeds are a Type of Sources; Endpoint agents and Watched devices are the two Types of Collectors. The Type choice is in the address.
- The Sources tab counts log sources only, as the Dashboard's Sources tile does; a problem on an enrichment feed still shows on the tab.
- Backups, Page rollups, and Speed moved to Settings > System, for administrators only. Analysts and Auditors no longer see these three lists. A failed backup still raises an alert, which everyone sees on the Dashboard and in Alerts.
- Old addresses still open their new places. For an Analyst or Auditor, an old Backups, Page rollups or Speed address opens System with a line saying it is for administrators.
- What you will notice: five fewer tabs on Health, a Type choice on Sources and Collectors, and System under Settings for administrators.
- What changes for existing installs: nothing to do. To go back, install the previous version with `update-systemd.sh --rollback` (docs/install/).
