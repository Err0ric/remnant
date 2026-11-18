### Logs: the query library is a tab (2026-11-17)

- Logs has a third tab, Library, beside Search and Saved searches, at its own address (`/investigate/library`), so a link or a refresh opens it.
- It lists every shipped, tested query by pack, each with its description, what is normal, and the sources it reads, with Run, Save as my own, and Add to dashboard. Run opens the query in the SQL editor over the last 24 hours; press Run there to see the results.
- A filter row finds a query by pack, name, or description.
- Queries for sources you have no events from are listed at the end under "Needs sources you don't have", with the names of those sources, instead of a count.
- Saved searches points to the Library; the Logs "..." menu and Ctrl+K "Logs › Library" open the tab.
- What you will notice: a Library tab on Logs lists the ready-made queries, including the ones waiting for a source you do not have yet.
- What changes for existing installs: nothing to do.
