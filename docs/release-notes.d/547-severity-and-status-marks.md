### Design: solid badges for Critical and High only, dots for the rest, sentence-case panel titles (2026-11-12)

- Console redesign, first half of build row 1b (ADR-0052 section 3.10, D248). Severity looks the same everywhere it appears (Logs, Alerts, the Dashboard's Needs attention list, rules, People & devices, mail rules): Critical and High are solid badges; Medium, Low, and Info are a small square dot followed by the word. Low is no longer blue. Every mark keeps its word.
- AI review status is a dot and the word: Approved a filled green dot, Unreviewed a hollow dot in the accent color, Not approved a hollow dot in the warning color. It no longer uses the red of a Critical alert, because a review status is not an alert; the same holds for the AI use chart on the Dashboard (Unreviewed in the accent color, Not approved in the warning color) and the "not approved in use" count on AI usage.
- Panel titles are 14px in sentence case; nothing in the app is set in upper case any more.
- What you will notice: fewer colored boxes on a calm screen, and only Critical and High stand out as filled badges.
- What changes for existing installs: nothing.
