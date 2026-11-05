### Ask answers with a headline and cited statements (2026-11-02)

- After the rows, **Ask** shows a one-line headline written from the result itself, for example "12 accounts with failed sign-ins; most: dana@example.com (40 failures)". It is never written by the model.
- Then, when the rows carry event ids, the model writes up to five statements about them, each with the event ids it is based on. A statement that cites none of the rows is removed, and Ask says how many were removed. If nothing can be cited, there is no summary: the headline and the rows stand alone.
- What the model said about its query moved under **How I got this**, so the space above the rows holds only what the rows support.
- New setting `ask.summarize` (default on; `APP__ASK__SUMMARIZE=false` to turn off): off, Ask makes no model call after the query, which suits slow CPU-only models.
- What changes for existing installs: nothing to do. Results without event ids, which includes most library queries, show the headline and rows without a summary for now.
