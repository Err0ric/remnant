### Ask answers, from anywhere (2026-11-02)

- **Ask** now runs its query as soon as it passes the safety checks, on your own sources, and shows the rows right under your question. The SQL, where the query came from, the sources read, and the time taken are under **How I got this**; **Edit as SQL** opens it in the SQL tab.
- Each question is a block; follow-ups stack below and refine the last one. People, addresses, and hosts in the rows open their pages.
- Ask from any page: press Ctrl+K and choose **Ask**, or type a sentence and choose **Ask "..."**. It opens beside the page.
- With a cloud model chosen, Ask says "Your question is sent to <provider>" under the question box.
- Ask now keeps each answer's SQL on the server, and `POST /api/ask/{ask_id}/run` runs exactly that SQL for the person who asked, through the same guard and on their own sources, capped at 1,000 rows and 90 days. Each run is in the audit log as a query with purpose `ask`.
- `remnant ask --yes` runs the answer without the prompt when the server allows auto-run and the SQL passed its self-check.
- What changes for existing installs: nothing to do. To keep click-to-run, set `ask.auto_run: false` in config/app.yaml.
