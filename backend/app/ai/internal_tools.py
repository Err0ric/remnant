"""Claude Code's own bookkeeping that arrives as tool calls (owner, 2026-11-03: a
subagent handing its result back showed as a "New tool" and in tool counts). These are not
tools a person or the model chose to use, so they are left out of new-item alerts, tool
lists, and tool counts. Their records stay in the lake and in a session's timeline.

One list, compared without case. Add a name here when Claude Code adds one."""

INTERNAL_TOOLS: tuple[str, ...] = ("subagenthandback",)

_IN = "(" + ", ".join(f"'{n}'" for n in INTERNAL_TOOLS) + ")"


def counted(expr: str) -> str:
    """SQL true when `expr` (a tool name) is a real tool call: not Claude Code bookkeeping.
    NULL stays NULL-safe: a row with no tool name is not a tool call either way."""
    return f"lower(coalesce({expr}, '')) NOT IN {_IN}"
