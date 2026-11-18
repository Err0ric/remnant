### Ask AI: results first, and no more "Can't reach the server" behind a slow proxy (2026-11-17)

- The Ask AI page now asks in the background and checks on the question every second or so, so no request stays open while the model works and a reverse proxy's time limit no longer ends a question.
- Each question shows its steps as they happen, Writing query, Running query, and Summarizing, the current one with the seconds so far and the finished ones with how long they took.
- The table shows as soon as the query has run; the summary fills in afterward. When the model takes too long to summarize, the table stays and one line under it says "The model took too long to summarize. Results are above."
- Across the app, a request a proxy gave up on says "The request took too long" (or "The server is busy"), and "Can't reach the server" shows only when the request got no answer at all.
- Ask no longer has a Cancel button: the server finishes the question it started.
- What you will notice: Ask AI shows the results table first with its progress steps, and a slow model no longer ends in "Can't reach the server" behind a proxy.
- What changes for existing installs: nothing to do.
