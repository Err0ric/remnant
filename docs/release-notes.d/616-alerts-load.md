### Alerts opens faster with many AI Watch alerts (2026-11-14)

- When many open AI Watch alerts name devices, the Alerts list looks up who used each device once per device instead of once per device and record. On synthetic data with 200 open alerts of 20 devices each and a month of hook records, the list went from about 1 second to 0.2 seconds. Who is named on each device, and what each viewer may see, is the same.
- Two page sections that both had to use disk space at the same time could spoil each other's temporary files, so one of them failed with a "Corrupt temporary file" error that read as a bad request. Each now keeps its own temporary files, and a page that runs out of memory always says so.
- What you will notice: Alerts opens faster when many AI Watch alerts are open.
- What changes for existing installs: nothing to do.
