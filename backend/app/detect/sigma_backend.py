"""pySigma backend that turns a Sigma rule's detection into a DuckDB condition (D7, ADR-0006).

The output is the WHERE condition only, written against the columns of the `events` view;
the runner wraps it in a SELECT over the caller's permitted, logsource-matched sources, and
the result still goes through the query guard like any other SQL.

Rules are untrusted input, so every value is written as a SQL string literal by this module
(quotes doubled, LIKE wildcards escaped) and never by string formatting of raw text:

| Sigma | DuckDB |
|---|---|
| `field: value` (also `*`, `?`) | `<field> ILIKE '<value>' ESCAPE '\\'` (case-insensitive) |
| `field|cased: value` | `<field> LIKE ... ESCAPE '\\'` |
| `field: 4624` | `<field> = '4624'` (text compare: a non-number never fails a cast) |
| `field|re: ...` | `regexp_matches(<field>, '...')`, flags inline (RE2: linear time) |
| `field|gt: 5` | `TRY_CAST(<field> AS DOUBLE) > 5` |
| keyword (no field) | `raw ILIKE '%...%'` |
| `field: null`, `|exists` | `IS NULL`, `IS NOT NULL` |
| `not ...` | `NOT coalesce((...), false)`: a missing field never makes a filter drop an event |

`<field>` comes from `pipelines/compat.field_expression`.
"""

from typing import Any, ClassVar

import duckdb
from sigma.conditions import (
    ConditionFieldEqualsValueExpression,
    ConditionNOT,
    ConditionValueExpression,
)
from sigma.conversion.base import TextQueryBackend
from sigma.conversion.state import ConversionState
from sigma.types import (
    CompareOperators,
    SigmaBool,
    SigmaNumber,
    SigmaRegularExpression,
    SigmaRegularExpressionFlag,
    SigmaString,
    SpecialChars,
)

from app.core.errors import RuleRejectedError
from app.detect.pipelines.compat import field_expression

_FLAGS = {
    SigmaRegularExpressionFlag.IGNORECASE: "i",
    SigmaRegularExpressionFlag.MULTILINE: "m",
    SigmaRegularExpressionFlag.DOTALL: "s",
}
_MAX_VALUE = 4_096  # characters in one value or pattern


def sql_literal(text: str) -> str:
    """A SQL string literal: the only quote character is doubled."""
    return "'" + text.replace("'", "''") + "'"


def like_pattern(s: SigmaString) -> str:
    """A LIKE pattern for ESCAPE '\\': Sigma wildcards become % and _, literal %, _ and \\
    are escaped."""
    out: list[str] = []
    for part in s.s:
        if isinstance(part, str):
            out.append(part.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))
        elif part == SpecialChars.WILDCARD_MULTI:
            out.append("%")
        elif part == SpecialChars.WILDCARD_SINGLE:
            out.append("_")
        else:
            raise RuleRejectedError("Placeholders in values are not supported")
    text = "".join(out)
    if len(text) > _MAX_VALUE:
        raise RuleRejectedError("A value in the rule is too long")
    return text


class _RegexCheck:
    """Rejects patterns RE2 cannot compile (lookarounds, backreferences) when the rule is
    converted, instead of failing every run later."""

    _con: ClassVar[duckdb.DuckDBPyConnection | None] = None

    @classmethod
    def valid(cls, pattern: str) -> bool:
        if cls._con is None:
            cls._con = duckdb.connect(":memory:", config={"enable_external_access": False})
        try:
            cls._con.execute("SELECT regexp_matches('', ?)", [pattern]).fetchall()
        except duckdb.Error:
            return False
        return True


class DuckDBBackend(TextQueryBackend):
    name: ClassVar[str] = "DuckDB (events view)"
    formats: ClassVar[dict[str, str]] = {"default": "WHERE condition on the events view"}
    requires_pipeline: ClassVar[bool] = False

    precedence: ClassVar[tuple[Any, Any, Any]] = TextQueryBackend.precedence
    group_expression: ClassVar[str] = "({expr})"
    token_separator: str = " "  # noqa: S105  # SQL operator, not a secret
    or_token: ClassVar[str] = "OR"  # noqa: S105  # SQL operator, not a secret
    and_token: ClassVar[str] = "AND"  # noqa: S105  # SQL operator, not a secret
    not_token: ClassVar[str] = "NOT"  # noqa: S105  # SQL operator, not a secret
    eq_token: ClassVar[str] = " = "  # noqa: S105  # SQL operator, not a secret

    # Every string match goes through like_pattern() and ILIKE, wildcards or not.
    eq_expression: ClassVar[str] = "{field} ILIKE {value} ESCAPE '\\'"
    wildcard_match_expression: ClassVar[str] = "{field} ILIKE {value} ESCAPE '\\'"
    case_sensitive_match_expression: ClassVar[str] = "{field} LIKE {value} ESCAPE '\\'"
    field_null_expression: ClassVar[str] = "{field} IS NULL"
    field_exists_expression: ClassVar[str] = "{field} IS NOT NULL"
    field_not_exists_expression: ClassVar[str] = "{field} IS NULL"
    field_equals_field_expression: ClassVar[str] = "lower({field1}) = lower({field2})"
    compare_op_expression: ClassVar[str] = "TRY_CAST({field} AS DOUBLE) {operator} {value}"
    compare_operators: ClassVar[dict[CompareOperators, str]] = {
        CompareOperators.LT: "<",
        CompareOperators.LTE: "<=",
        CompareOperators.GT: ">",
        CompareOperators.GTE: ">=",
    }
    unbound_value_str_expression: ClassVar[str] = "raw ILIKE '%' || {value} || '%' ESCAPE '\\'"
    unbound_value_num_expression: ClassVar[str] = "raw ILIKE '%{value}%'"
    re_expression: ClassVar[str] = "regexp_matches({field}, {regex})"
    unbound_value_re_expression: ClassVar[str] = "regexp_matches(raw, {value})"
    bool_values: ClassVar[dict[bool, str | None]] = {True: "'true'", False: "'false'"}

    def convert_condition_not(self, cond: ConditionNOT, state: ConversionState) -> str | None:
        """SQL is three-valued: NOT (NULL ILIKE '-') is NULL and the row would be dropped.
        In Sigma an event without the field does not match the filtered value, so the
        negated part counts as false when it is NULL."""
        arg = cond.args[0]
        if arg is None:
            return None
        inner = self.convert_condition(arg, state)
        if not isinstance(inner, str):
            raise RuleRejectedError("Deferred expressions are not supported")
        return f"NOT coalesce(({inner}), false)"

    # Sigma field name to the name the events use, applied before field_expression().
    field_map: ClassVar[dict[str, str]] = {}

    def escape_and_quote_field(self, field_name: str) -> str:
        return field_expression(self.field_map.get(field_name, field_name))

    def convert_value_str(self, s: SigmaString, state: ConversionState) -> str:
        return sql_literal(like_pattern(s))

    def convert_condition_field_eq_val_str_case_sensitive(
        self, cond: ConditionFieldEqualsValueExpression, state: ConversionState
    ) -> str:
        value = cond.value
        if not isinstance(value, SigmaString):
            raise RuleRejectedError("Expected a string value")
        return self.case_sensitive_match_expression.format(
            field=self.escape_and_quote_field(cond.field),
            value=self.convert_value_str(value, state),
        )

    def convert_condition_field_eq_val_num(
        self, cond: ConditionFieldEqualsValueExpression, state: ConversionState
    ) -> str:
        if not isinstance(cond.value, SigmaNumber):
            raise RuleRejectedError("Expected a number")
        number = cond.value.number
        return f"{self.escape_and_quote_field(cond.field)} = {sql_literal(str(number))}"

    def convert_condition_field_eq_val_bool(
        self, cond: ConditionFieldEqualsValueExpression, state: ConversionState
    ) -> str:
        if not isinstance(cond.value, SigmaBool):
            raise RuleRejectedError("Expected true or false")
        token = self.bool_values[cond.value.boolean]
        return f"lower({self.escape_and_quote_field(cond.field)}) = {token}"

    def _regex(self, r: SigmaRegularExpression) -> str:
        flags = "".join(sorted(_FLAGS[f] for f in r.flags if f in _FLAGS))
        if len(flags) != len(r.flags):
            raise RuleRejectedError("Unsupported regular expression flag")
        source = getattr(r.regexp, "original", None) or str(r.regexp)  # the pattern as written
        pattern = (f"(?{flags})" if flags else "") + source
        if len(pattern) > _MAX_VALUE:
            raise RuleRejectedError("A regular expression in the rule is too long")
        if not _RegexCheck.valid(pattern):
            raise RuleRejectedError("Regular expression not supported (RE2 syntax only)")
        return sql_literal(pattern)

    def convert_condition_field_eq_val_re(
        self, cond: ConditionFieldEqualsValueExpression, state: ConversionState
    ) -> str:
        value = cond.value
        if not isinstance(value, SigmaRegularExpression):
            raise RuleRejectedError("Expected a regular expression")
        return self.re_expression.format(
            field=self.escape_and_quote_field(cond.field), regex=self._regex(value)
        )

    def convert_condition_val_re(
        self, cond: ConditionValueExpression, state: ConversionState
    ) -> str:
        value = cond.value
        if not isinstance(value, SigmaRegularExpression):
            raise RuleRejectedError("Expected a regular expression")
        return self.unbound_value_re_expression.format(value=self._regex(value))


class SecurityAuditBackend(DuckDBBackend):
    """Process creation through Security event 4688 instead of Sysmon event 1: the Sysmon
    field names that 4688 also records, under their 4688 names (as pySigma's Windows audit
    pipeline maps them). Used only for rules whose fields are all in `field_map` or need no
    mapping; see rules.AUDIT_4688_FIELDS."""

    field_map: ClassVar[dict[str, str]] = {
        "Image": "NewProcessName",
        "ParentImage": "ParentProcessName",
        "LogonId": "SubjectLogonId",
    }
