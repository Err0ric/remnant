### Health: one filter row and calmer rows (2026-11-14)

- Health has one filter row: Status (All, Problems, Paused, Healthy, with counts) and Type, with the number of rows at the right. Problems holds what was Unhealthy and Needs attention.
- A tab shows a number only when something on it needs attention, outlined in orange; there are no totals beside the tabs.
- The four numbers at the top look like the Dashboard's, in one strip; Alert delivery reads "0 failed" with "All delivered" under it. The sentence "No detections in 24 hours..." is gone; the detections and paused schedules card shows only when it has something to list.
- The Sources list has Status and Peak columns, and Last received shows the time in your local format (UTC on hover). A source that is only quiet is drawn in grey; a gap keeps its red shading and sentence.
- While Health loads, the numbers show grey bars instead of zeros or "All delivered".
- Old Health addresses (the former tabs) still open the same view.
- If part of Health cannot be read, its numbers say "Could not load" with Retry instead of showing zeros.
- What you will notice: Health has one filter row, tab numbers only for problems, and no all-clear before it has checked.
- What changes for existing installs: nothing to do.
