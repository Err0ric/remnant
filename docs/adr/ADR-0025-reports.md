# ADR-0025: Executive and detailed reports as PDF, monthly or for any range

Status: **Accepted** 2026-10-20 (project owner: "monthly but being able to set custom range would be nice", "PDF should be fine", "just a good looking PDF with the high level metrics showing"). Recorded as SPEC D67; answers open question Q2; threat T56 added.

## Context

Owners of a small security program report upward every month and keep a fuller record for themselves and auditors. Today the product has the numbers spread across pages (Overview, Health, AI usage, Detections, Audit, Integrity) and one Markdown report draft from Explain. Nothing produces a single document for a period.

## Decision

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Report types | **Executive** (2 pages at most) and **Detailed** (as long as the data) | One for leadership, one for the analyst and auditors |
| 2 | Period | Last calendar month by default; any custom range up to 366 days. Every figure is compared with the period of the same length just before | Monthly is the usual rhythm; the comparison is what leadership reads |
| 3 | Executive contents | Period, sources in scope, generated time. Headline figures with change: events stored, detections by severity, alerts sent, sources that went quiet, new AI services and MCP servers, AI not approved in use, sensitive-data signals, integrity result (with seal number). One chart each: daily events, detections per week by severity. Top 5: rules by matches, hosts and users by detections, AI services by people. 3 to 5 summary bullets written from fixed templates ("Detections rose 40% against September, mostly from rule X") | High-level, every number traceable |
| 4 | Detailed contents | Everything in the executive report, plus: per-source volume and gaps, every detection rule and flagged search with counts, health issues, full AI usage tables (with New and No longer seen, D66), admin changes and exports from the audit log, failed sign-ins, AI calls by provider and purpose | The record behind the summary |
| 5 | Where numbers come from | The deterministic engine only, through the guard, from the requesting user's `events` view and the stores each page already reads. Nothing is estimated | Rules 1, 7, 13 |
| 6 | AI-written summary | Optional, off by default. When on, the model receives only the report's aggregate figures and top lists as JSON under `data` (never event content), writes at most 5 bullets, and every bullet must cite figure keys from that JSON; bullets that fail the check are dropped. Through the gate, audited, local-only rules apply | Low injection surface (AML.T0051): no log lines reach the prompt |
| 7 | Format | PDF rendered on the server from an HTML template with inline SVG charts (WeasyPrint), using the product's tokens in light theme for print. Also a preview page in the app and a CSV of the figures | PDF is what gets attached and forwarded; server-side so schedules can send it |
| 8 | Scheduling and delivery | A report can be scheduled monthly (runs on the 1st for the month before) or weekly. Runs as the owner with permissions re-checked, like saved-search schedules (ADR-0008). Email targets get the PDF attached (capped at 10 MB); Teams, Slack, and webhooks get the headline figures and a link to download it in the app | Reuses targets and the schedule model |
| 9 | Storage | Generated PDFs kept under `data/reports/` with a row in `meta.sqlite` (owner, type, period, sources in scope, SHA-256); last 24 per schedule | Re-download and prove what was sent |
| 10 | Who | Admins and auditors generate any report over their own scope; analysts generate reports over their own scope; every generation and download is audited (`report.generate`, `report.download`) | Rule 14 |
| 11 | Build order | (a) Executive report, custom range, preview and PDF download. (b) Detailed report. (c) Monthly schedule and email delivery. (d) Optional AI summary | Thin slices, each usable on its own |

## Consequences

- New runtime dependency: WeasyPrint, which needs Pango and HarfBuzz in the image; the image grows. Fonts are the bundled UI fonts, so no font is fetched.
- The report builder reads from existing services (Overview, Health, AI usage, rule runs, schedules, audit, integrity); no new event queries beyond daily and weekly counts.
- A PDF can hold `local_only` figures and host or user names. Email delivery of a report that includes `local_only` sources follows ADR-0024 row 5: only to targets whose every address is private; otherwise the email carries headline figures only and the link.
- Not AI-facing unless row 6 is turned on. With it on: AML.T0051 (indirect prompt injection) is limited because only aggregates are sent; AML.T0057 (data leakage) is handled by the gate's classification block and audit.
- Threats: T56 (a report leaks data a recipient should not see: built from the owner's scope, re-checked each run, `local_only` held back from non-private targets, every send audited).
