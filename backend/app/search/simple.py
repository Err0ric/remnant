"""Simple search: Kibana/Lucene-style text compiled to SQL without a model (ADR-0009).

    sshd "failed password" -user:root src_ip:203.0.113.* severity:>=high

- Bare words and "quoted phrases" match `raw` or `message`, case-insensitive, anywhere.
- `field:value` compares a field. Names are schema columns, the short aliases below, or
  Sigma field names (`EventID`, `TargetUserName`, ...), which read `unmapped` the same way
  rules do (`detect/pipelines/compat.py`). Text matches ignore case; `*` is a wildcard;
  `field:*` means the field has a value. Numbers and times take `>`, `>=`, `<`, `<=`;
  a time given as a date alone (`time:2026-10-10`) means that whole day, UTC.
- `AND`, `OR`, `NOT` or a leading `-`, and parentheses. Words side by side mean AND.
- A backslash makes the next character literal (`\\*`, `\\:`, `\\-`).

Nothing typed ever becomes SQL text: field names are looked up in fixed tables (or, for
Sigma names, must be letters, digits, `_`, `.`, `-`), and every value is a bound
parameter. Wildcards become `ILIKE` with `%`, `_`, and `\\` escaped, so there is no regex
and no backtracking. The SQL still runs through the guard and the caller's `events` view.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.errors import RuleRejectedError, SearchInvalidError
from app.core.schema import COLUMNS, ColumnType
from app.detect.pipelines.compat import FIELD_EXPRESSIONS, field_expression

MAX_TEXT = 2048
MAX_TERMS = 50
MAX_DEPTH = 20
TOP_LIMIT = 20

RESULT_COLUMNS = (
    "time, severity_id, source_id, device_hostname, actor_process_name, message, event_id"
)

# Short names for the columns people search most. Full column names always work too.
ALIASES: dict[str, str] = {
    "user": "actor_user_name",
    "src_ip": "src_endpoint_ip",
    "dst_ip": "dst_endpoint_ip",
    "src_port": "src_endpoint_port",
    "dst_port": "dst_endpoint_port",
    "host": "device_hostname",
    "process": "actor_process_name",
    "source": "source_id",
    "severity": "severity_id",
}

# OCSF severity_id by name, so `severity:high` and `severity:>=medium` read naturally.
SEVERITY_NAMES: dict[str, int] = {
    "unknown": 0,
    "informational": 1,
    "info": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
    "fatal": 6,
}

_TYPES: dict[str, ColumnType] = {c.name: c.type for c in COLUMNS}
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]{0,127}")
_OPS = (">=", "<=", ">", "<")
_WILD = object()  # a wildcard position inside a value


@dataclass(frozen=True, slots=True)
class Compiled:
    sql: str
    params: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    # Schema columns the search filters on, so the UI can say when one is empty.
    columns: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: str  # term | and | or | not | ( | )
    field: str | None = None
    op: str = "="
    parts: tuple[Any, ...] = ()  # text pieces and _WILD markers
    pos: int = 0


def compile_search(text: str, top: str | None = None) -> Compiled:
    """SQL and parameters for `text`; with `top`, counts per value of that field instead."""
    if len(text) > MAX_TEXT:
        raise SearchInvalidError(f"The search is too long (over {MAX_TEXT} characters)")
    tokens = _tokenize(text)
    terms = sum(1 for t in tokens if t.kind == "term")
    if terms > MAX_TERMS:
        raise SearchInvalidError(f"The search has too many terms (over {MAX_TERMS})")
    builder = _Builder(tokens)
    where = builder.where()
    clause = f"\nWHERE {where}" if where else ""
    if top is None:
        sql = (
            f"SELECT {RESULT_COLUMNS}\nFROM events{clause}\n"
            "ORDER BY coalesce(time, time_observed) DESC"
        )
    else:
        expr, _kind, label = builder.resolve(top.strip(), -1)
        sql = (
            f'SELECT {expr} AS "{label}", count(*) AS events\nFROM events{clause}\n'
            f"GROUP BY 1\nORDER BY 2 DESC, 1\nLIMIT {TOP_LIMIT}"
        )
    return Compiled(sql, builder.params, builder.notes, builder.columns)


# --- tokens ---------------------------------------------------------------------------------


def _tokenize(text: str) -> list[_Tok]:
    out: list[_Tok] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            out.append(_Tok(c, pos=i))
            i += 1
        elif c == "-" and i + 1 < n and not text[i + 1].isspace() and text[i + 1] != ")":
            out.append(_Tok("not", pos=i))
            i += 1
        elif c == '"':
            phrase, end = _phrase(text, i)
            out.append(_Tok("term", parts=(phrase,), pos=i))
            i = end
        else:
            out.append(_word(text, i))
            i = _word_end(text, i)
    return out


def _phrase(text: str, start: int) -> tuple[str, int]:
    """A quoted phrase starting at text[start] == '"'; everything inside is literal."""
    chars: list[str] = []
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            chars.append(text[i + 1])
            i += 2
        elif c == '"':
            return "".join(chars), i + 1
        else:
            chars.append(c)
            i += 1
    raise SearchInvalidError(f"A quote opened at character {start + 1} is never closed")


def _word_end(text: str, i: int) -> int:
    while i < len(text) and not text[i].isspace() and text[i] not in "()":
        if text[i] == "\\":
            i += 1
        elif text[i] == '"':
            _, i = _phrase(text, i)
            continue
        i += 1
    return min(i, len(text))


def _word(text: str, start: int) -> _Tok:
    end = _word_end(text, start)
    raw = text[start:end]
    if raw in ("AND", "OR", "NOT"):  # upper case only, as in Lucene; "and" is a word
        return _Tok(raw.lower(), pos=start)
    name: str | None = None
    body_at = start
    m = _FIELD.match(raw)
    if m and m.end() < len(raw) and raw[m.end()] == ":":
        name = m.group(0)
        body_at = start + m.end() + 1
    op = "="
    if name is not None:
        for candidate in _OPS:
            if text.startswith(candidate, body_at):
                op = candidate
                body_at += len(candidate)
                break
    parts = _value(text, body_at, end)
    if name is not None and not parts:
        raise SearchInvalidError(f"Give a value after {name}: (for example {name}:value)")
    return _Tok("term", field=name, op=op, parts=parts, pos=start)


def _value(text: str, i: int, end: int) -> tuple[Any, ...]:
    """Text pieces and wildcard markers; quoted parts and escaped characters are literal."""
    parts: list[Any] = []
    buf: list[str] = []
    while i < end:
        c = text[i]
        if c == "\\" and i + 1 < end:
            buf.append(text[i + 1])
            i += 2
        elif c == '"':
            phrase, i = _phrase(text, i)
            buf.append(phrase)
        elif c == "*":
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append(_WILD)
            i += 1
        else:
            buf.append(c)
            i += 1
    if buf:
        parts.append("".join(buf))
    return tuple(parts)


# --- parsing and SQL ------------------------------------------------------------------------


class _Builder:
    def __init__(self, tokens: list[_Tok]) -> None:
        self._t = tokens
        self._i = 0
        self._depth = 0
        self.params: dict[str, Any] = {}
        self.notes: list[str] = []
        self.columns: list[str] = []

    def where(self) -> str:
        if not self._t:
            return ""
        sql = self._or()
        if self._i < len(self._t):
            tok = self._t[self._i]
            raise SearchInvalidError(
                f"Unexpected {_describe(tok)} at character {tok.pos + 1}"
                + (" (no matching opening parenthesis)" if tok.kind == ")" else "")
            )
        return sql

    def _peek(self) -> str | None:
        return self._t[self._i].kind if self._i < len(self._t) else None

    def _or(self) -> str:
        items = [self._and()]
        while self._peek() == "or":
            self._i += 1
            items.append(self._and())
        return items[0] if len(items) == 1 else "(" + " OR ".join(items) + ")"

    def _and(self) -> str:
        items = [self._unary()]
        while self._peek() not in (None, "or", ")"):
            if self._peek() == "and":
                self._i += 1
            items.append(self._unary())
        return items[0] if len(items) == 1 else "(" + " AND ".join(items) + ")"

    def _unary(self) -> str:
        if self._peek() == "not":
            self._i += 1
            self._enter()
            inner = self._unary()
            self._depth -= 1
            return f"NOT {inner}"
        return self._primary()

    def _primary(self) -> str:
        if self._i >= len(self._t):
            raise SearchInvalidError("The search ends where a term was expected")
        tok = self._t[self._i]
        self._i += 1
        if tok.kind == "(":
            self._enter()
            inner = self._or()
            if self._peek() != ")":
                raise SearchInvalidError(
                    f"The parenthesis at character {tok.pos + 1} is never closed"
                )
            self._i += 1
            self._depth -= 1
            return inner
        if tok.kind == "term":
            return self._term(tok)
        raise SearchInvalidError(f"Unexpected {_describe(tok)} at character {tok.pos + 1}")

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise SearchInvalidError(f"The search nests too deeply (over {MAX_DEPTH} levels)")

    def _param(self, value: Any) -> str:
        name = f"p{len(self.params)}"
        self.params[name] = value
        return f"${name}"

    # --- one term -------------------------------------------------------------------------

    def _term(self, tok: _Tok) -> str:
        if tok.field is None:
            if tok.op != "=":
                raise SearchInvalidError("Use > and < after a field name, as in severity:>=4")
            p = self._param(_like(tok.parts, contains=True))
            # A term is never NULL, so NOT and - behave as people expect on empty fields.
            return f"coalesce(raw ILIKE {p} ESCAPE '\\' OR message ILIKE {p} ESCAPE '\\', false)"
        expr, kind, label = self.resolve(tok.field, tok.pos)
        if expr == f'"{label}"' and label not in self.columns:
            self.columns.append(label)
        return f"coalesce({self._compare(tok, expr, kind)}, false)"

    def resolve(self, name: str, pos: int) -> tuple[str, ColumnType, str]:
        """(SQL expression, type, label) for a field name typed by the user."""
        column = ALIASES.get(name) or ALIASES.get(name.lower())
        if column is None and (name in _TYPES or name.lower() in _TYPES):
            column = name if name in _TYPES else name.lower()
        if column is not None:
            return f'"{column}"', _TYPES[column], column
        if not _FIELD.fullmatch(name):
            raise SearchInvalidError(f"{name[:60]!r} is not a field name")
        try:
            expr = field_expression(name)
        except RuleRejectedError as exc:
            raise SearchInvalidError(f"{name[:60]!r} is not a field name") from exc
        if name not in FIELD_EXPRESSIONS:
            note = f"{name} is not a column, so it is looked up in unmapped fields"
            if note not in self.notes:
                self.notes.append(note)
        return expr, ColumnType.STRING, name

    def _compare(self, tok: _Tok, expr: str, kind: ColumnType) -> str:
        parts = tok.parts
        if parts == (_WILD,):
            if tok.op != "=":
                raise SearchInvalidError(f"{tok.field}:* cannot take {tok.op}")
            return f"{expr} IS NOT NULL" + (
                f" AND CAST({expr} AS VARCHAR) <> ''" if kind != ColumnType.TIMESTAMPTZ else ""
            )
        wild = _WILD in parts
        text = "".join(p for p in parts if p is not _WILD)
        if kind in (ColumnType.STRING, ColumnType.JSON):
            if tok.op != "=":
                n = _number(text)
                if n is None or wild:
                    raise SearchInvalidError(
                        f"{tok.field}:{tok.op} needs a number; text fields take = only"
                    )
                return f"TRY_CAST({expr} AS DOUBLE) {tok.op} {self._param(n)}"
            if wild:
                return f"{expr} ILIKE {self._param(_like(parts, contains=False))} ESCAPE '\\'"
            return f"lower({expr}) = lower({self._param(text)})"
        if wild:
            raise SearchInvalidError(f"{tok.field} is not a text field, so * does not apply")
        if kind == ColumnType.INT:
            value = SEVERITY_NAMES.get(text.lower()) if expr == '"severity_id"' else None
            if value is None:
                try:
                    value = int(text)
                except ValueError:
                    raise SearchInvalidError(f"{tok.field} needs a whole number") from None
            if not -(2**63) <= value < 2**63:
                raise SearchInvalidError(f"{tok.field}: the number is out of range")
            return f"{expr} {tok.op} {self._param(value)}"
        if kind == ColumnType.BOOL:
            if tok.op != "=" or text.lower() not in ("true", "false"):
                raise SearchInvalidError(f"{tok.field} takes true or false")
            return f"{expr} = {self._param(text.lower() == 'true')}"
        return self._time(tok, expr, text)

    def _time(self, tok: _Tok, expr: str, text: str) -> str:
        day = _date(text)
        if day is not None:
            start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            if tok.op == "=":
                lo, hi = self._ts(start), self._ts(start + timedelta(days=1))
                return f"({expr} >= {lo} AND {expr} < {hi})"
            # A whole day: "after 10 Oct" starts the next day; "up to 10 Oct" includes it.
            if tok.op in (">", "<="):
                start += timedelta(days=1)
            op = {">": ">=", ">=": ">=", "<": "<", "<=": "<"}[tok.op]
            return f"{expr} {op} {self._ts(start)}"
        moment = _datetime(text)
        if moment is None:
            raise SearchInvalidError(
                f"{tok.field} needs a date or time such as 2026-10-10 or 2026-10-10T14:30Z"
            )
        return f"{expr} {tok.op} {self._ts(moment)}"

    def _ts(self, value: datetime) -> str:
        return f"CAST({self._param(value.isoformat())} AS TIMESTAMPTZ)"


def _like(parts: tuple[Any, ...], contains: bool) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    body = "".join("%" if p is _WILD else esc(p) for p in parts)
    return f"%{body}%" if contains else body


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _date(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise SearchInvalidError(f"{text!r} is not a real date") from None


def _datetime(text: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _describe(tok: _Tok) -> str:
    return {"and": "AND", "or": "OR", "not": "NOT", "(": "(", ")": ")"}.get(tok.kind, "term")
