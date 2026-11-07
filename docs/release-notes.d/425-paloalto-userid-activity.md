### Plain names for User-ID activities (2026-11-06)

- Palo Alto User-ID lines now read as "User-ID login", "User-ID logout", "User-ID tag registered", or "User-ID tag removed" in messages and on the person page's "How it connects" lanes, instead of the CSV line with its digits masked. The data source name moves to unmapped.
- An activity whose lines carry no message, or a message that is a whole delimited record, is named by its template (or its event class) on the investigator graph, and its card still opens a search for exactly those lines.
- What changes for existing installs: User-ID events ingested from now on get the plain message (template 1.2.0); events already in the lake keep their stored message, and the graph names them by template where that message was the raw record.
