### AI usage opens faster on large installs (2026-11-14)

- AI usage reads the period before the chosen range at the same time as the range itself, instead of after it.
- The first day of a range is read from the daily AI summary for its whole hours after the start, and only the rest of the start's own hour from the raw events, when that day's summary is complete with who had which address. A day whose summary is not ready yet is still read from the events. The AI inventory, which asks the same question, reads it the same way. Every number on both stays the same.
- A start sent with a time zone offset of half or three quarters of an hour (for example +05:30) is now cut at the UTC hour the summaries are kept by; before, a start on such a zone's hour could leave out up to an hour of use after it.
- What you will notice: AI usage and the AI inventory open faster on large installs.
- What changes for existing installs: nothing to do.
