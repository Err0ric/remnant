### Logs and Ask AI: one name per thing (2026-11-04)

- **Search** is now **Logs** in the left nav and the Investigate tabs, at `/investigate/logs`. Its modes are **Filters** (what the Search tab was) and **SQL**.
- **Ask** is now **Ask AI**, its own page at `/ask-ai`, no longer a tab inside Logs. It has its own time range and source filter. The Ctrl+K panel is titled Ask AI too.
- Each answer keeps **How I got this** and now shows **Open in Logs**, which opens the answer's SQL in the Logs SQL mode with the same time range and sources. It replaces Edit as SQL. Saving it there keeps your question as the saved search's origin.
- Buttons and links that said "Open in Search" now say "Open in Logs". In the command palette, "search" and "ask" still find Logs and Ask AI.
- What changes for existing installs: nothing to do. Old addresses (`/search`, `/investigate/search`, `/ask`) and bookmarks open the new pages with the same search, and recent searches still open. A browser that last used the Ask tab opens Logs on Filters.
