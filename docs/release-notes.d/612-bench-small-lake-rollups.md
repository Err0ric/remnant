### The speed check's lake is kept as an install keeps its data (2026-11-14)

- The speed check's default lake, the one the merge queue times every change on, is now kept compacted with its daily rollups built, as the 30-day lake already was. Before, each timed server built those rollups while it was being timed, so pages read those days from raw events meanwhile.
- A kept lake is built again once for this, and from now on once each UTC day (a lake built before midnight has a new day with no rollup after it). A build takes about three minutes longer (97 s to 279 s).
- On the kept lake the rows read what an install's pages cost: in the first tables the Dashboard row went from 0.80 to 0.66 s, AI usage from 0.43 to 0.35 s, People & devices from 0.64 to 0.52 s, and the Person page stayed at about 4.2 s, on both sides alike.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do.
