### Logs reads the newest day first (2026-11-14)

- A Logs search over a long window reads the newest day's files first and goes back only as far as it must to fill the page, so a 30-day search with matches on the newest day costs about what a one-day search costs.
- The rows, their order, and the count are the same as before; when two events have the same time, the one with the higher event id comes first, every time.
- A search with no match in the newest day reads that day first and then the rest, so it can take slightly longer: on a 30-day lake at the size of a production install, a search with no match at all took 2.4 s instead of 2.1 s.
- SQL typed in the SQL tab, saved searches written as SQL, and SQL another page hands over run as written. The Fields panel and the field check still count over the whole window.
- What you will notice: long Logs searches show their results sooner.
- What changes for existing installs: nothing to do.
