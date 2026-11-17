### Settings > Sources: one status with Health, parser updates folded away (2026-11-16)

- Settings > Sources shows each source's status in the same words and dot as Health ("Flowing", "Idle", "Quiet 5 d", "Never sent", "Paused", "Unhealthy"), from the one rule the server uses for both. A file that is still being read but has sent nothing for days now reads as quiet on both pages, not as green "Reading".
- What the reader is doing is its own small line under the status, for example "Reader: following the files".
- Parser updates are one line with a closed "What changed" that lists each update in plain words and the searches to check; column names and decision numbers are no longer on the page.
- The "Local only" badge and the "latest ... ago" line no longer break over two lines.
- The Dashboard's Needs you names a source by the same status ("Quiet 33 h", "Unhealthy") with what is wrong ("dns_bind: nothing received for 33 h"), and lists no source that is quiet as normal or paused.
- What you will notice: Settings > Sources and the Dashboard say the same status as Health for every source, and parser updates take one line until you open What changed.
- What changes for existing installs: nothing to do.
