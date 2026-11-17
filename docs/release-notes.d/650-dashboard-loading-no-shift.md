### Dashboard: loads in its final layout, with nothing moving (2026-11-17)

- The Dashboard draws every part in its final place at once: the key numbers have all their tiles from the start, each a placeholder until its number arrives, and AI Watch, Identity, Attacks and access, and Detections each show their title and cards while their numbers load, in a box of the same size they have when loaded.
- Nothing jumps when a number arrives: the Needs you list, the key numbers, and every section header stay where they first appeared.
- Each section keeps the height it had the last time you opened the Dashboard in this browser, so returning visits load with no empty space; a first visit sizes each section by the time window.
- What is already known to be empty is drawn at its own size from the start: Detections when no rule is enabled and no match is kept from before (administrators only, with Enable rules; others do not see the section, as before), and Attacks and access when the sources it counts sent nothing in the window. Matches kept from rules turned off still show.
- If your list of sources cannot be read, every section still loads on its own, with Retry for the list.
- A tile with nothing to count keeps its place: AI services in use reads 0 ("None in this window"), and a tile without data says "Not available". A section with nothing to show says so, centered in its box: "No sign-in failures from external addresses in this window.", "No AI use in sources you can read."
- Loading placeholders are easier to see in the dark theme.
- The smoke test now loads the Dashboard with its answers held back and fails when anything on it moves.
- What you will notice: the Dashboard no longer jumps while it loads; every section shows its title and grey placeholders until its numbers arrive.
- What changes for existing installs: nothing to do.
