### Two flaky tests made steady; a quick quit of the terminal app no longer shows an error (2026-11-14)

- `remnant tui`: when the list of sources arrived while the app was closing, filling it could fail and print an error on exit. A list that arrives at that moment is now ignored, as one that arrives after the app has closed already was.
- The merge queue's lock (developer tooling): where `mkdir` lets two takers in at once, the taker that had just written the lock could see the other one enter the guard as it left it, report the guard as changed, and give up, so neither queue held the lock. Leaving the guard is now not counted as a change; the lock is still checked to be its own.
- Both tests now hold the moment that went wrong still, so they fail every time the fault comes back instead of once in a while on a busy machine.
- What you will notice: quitting `remnant tui` quickly no longer prints an error; nothing else visible.
- What changes for existing installs: nothing to do.
