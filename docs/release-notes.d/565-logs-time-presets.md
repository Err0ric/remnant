### Design: Logs and Ask AI use the same five time choices (2026-11-13)

- Console redesign, build row 7, time controls, part 2 (ADR-0052 section 3.7; owner, 2026-11-13). The time filter of Logs and of Ask AI is 1 hour, 24 hours, 7 days, 30 days, or Custom, as on Alerts. Custom is a start and an end in your own time zone (hover for UTC); an empty side is open.
- "Last 15 minutes" and "All time" are gone. Custom with no dates is everything kept, which is what a query opened from another page (a rule's matches, Ask AI's "Open in Logs") now opens on.
- Old links keep working: an address with All time opens as Custom with no dates, and one with 15 minutes opens on 1 hour. A number opened from the Dashboard still shows exactly its own window, now as Custom with its two dates, and keeps it through a reload. A link with a Custom range opens on the same moments for a reader in another time zone.
- What you will notice: time is five buttons on Logs and Ask AI, with two date boxes for Custom.
- What changes for existing installs: nothing to do. Bookmarks keep working.
