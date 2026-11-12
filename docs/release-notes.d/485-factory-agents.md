### Reviewer, designer, and tester agents for development (2026-11-10)

- Three Claude Code subagents in `.claude/agents/` for building this project: a reviewer that reads only CLAUDE.md, the PR's ADR or handoff item, and the diff, and posts one ranked comment; a designer and a tester that work only on the synthetic demo and write proposals to `docs/proposals/`. None of them edits code, approves, or merges.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Development files only; nothing in the app, data, settings, or update steps changes.
