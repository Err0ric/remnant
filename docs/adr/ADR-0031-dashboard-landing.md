# ADR-0031: Dashboard first when it has panels

Status: **Accepted** 2026-10-21 (project owner: option (a) now; a merged Home page later). Supersedes the landing-page part of D34 (ADR-0008). Recorded as SPEC D83.

## Context

D34 made Overview the landing page: whether ingest, detections, and alert delivery are healthy. In the install trial, the page people actually opened first was the Dashboard, with the scheduled searches they had built for their own work, and it sat last in the nav under Detect.

Options the owner weighed:

| Option | What | Cost |
|---|---|---|
| (a) | Dashboard first in the nav, and the landing page when the viewer has at least one panel; Overview otherwise. A compact health strip from Overview at the top of the Dashboard | Small; no new page |
| (b) | One merged Home page: Overview's health cards and the Dashboard panels together | A new page and layout; later |

## Decision

| # | Decision |
|---|---|
| 1 | Nav: **Dashboard** is the first item under General, before Overview, and leaves the Detect group (one place only) |
| 2 | Landing: the root address, the product mark in the top bar, and sign-in open the Dashboard when the viewer sees at least one panel (a schedule they own, a shared one, or any as an admin), and Overview otherwise, including when the schedule list cannot be loaded. Unknown paths still open Overview. `/overview` and `/dashboard` are unchanged |
| 3 | Health on the first screen either way: the Dashboard opens with one line from Overview's data (sources behind or quiet, paused schedules, failing alert targets, each a count) and a link to Overview. All clear says so in one phrase |
| 4 | Option (b), a merged Home page, goes to `docs/BACKLOG.md` |

## Consequences

- People with panels land on their own work; a new install with no schedules still lands on Overview, which explains what to set up.
- Loading the Dashboard also reads `/api/overview` for the strip, so it writes the same `overview.view` audit row Overview does.
- No API, permission, or data change.

## Threat model

No AI-facing change; nothing new in SPEC section 7.
