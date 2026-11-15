### Long names and emails cut where they hurt least (2026-11-14)

- An email address keeps the part before the "@" for as long as it can: the domain is greyed and is cut first.
- Long names such as source ids, hosts, apps, and networks are cut in the middle and keep their last 8 characters, so `m365_management_activity` reads as its start, "…", and "activity". Hover shows the whole value (and keyboard focus does, on values that are not links), and copying gives each value whole, on one line, however much you select.
- On the Dashboard, Needs you reads severity, kind, who or what, what happened, then when, with no wide gap before the name. Alert titles there and in the Alerts queue use up to two lines before they are cut.
- The Network column of Top sources and the App column of "Apps signed in to" get the free space of their card; the Person column on AI usage > People is wide enough that an email never breaks inside a word.
- While AI usage and Agents load, the grey placeholder rows have the shape of the table, and the "Needs attention" line keeps its place, so the page no longer jumps when the data arrives. If AI usage cannot be loaded, the error shows without a placeholder above it.
- Not done yet: hiding your organization's own domain in emails.
- What you will notice: long names and emails are cut in the middle or at the domain with the full value on hover, and AI usage no longer jumps while it loads.
- What changes for existing installs: nothing to do.
