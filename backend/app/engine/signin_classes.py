"""How a failed Microsoft Entra sign-in is counted, by error code (D158).

The shipped classes are in `app/content/m365/signin_codes.yaml`; an install can move codes
between classes with `m365.signin_classes` in its config, without editing that file. The
engine defines the SQL macro `signin_class(code)` on every query connection from the
classes in force, so the Dashboard, Microsoft 365, the fact rollup's days, and Search all
read one definition, and a change applies to stored events at once (nothing is
re-parsed). A failed sign-in whose code is in no class is "other": counted apart, never
dropped.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast, get_args

import yaml

SignInClass = Literal["failed", "interrupted", "expired", "other"]
CLASSES: Final[tuple[SignInClass, ...]] = get_args(SignInClass)
CODES_FILE: Final[Path] = (
    Path(__file__).resolve().parents[1] / "content" / "m365" / "signin_codes.yaml"
)
BLOCKED_CODE: Final[int] = 53003  # Conditional Access: a failure, also shown on its own

# The error code of a sign-in: the column (m365_signin 1.2.0 on), else Entra's record.
CODE_SQL: Final[str] = (
    "coalesce(TRY_CAST(status_code AS INTEGER),"
    " TRY_CAST(TRY(json_extract_string(raw, '$.status.errorCode')) AS INTEGER))"
)
# Interactive or not: the column, else the record; NULL when neither says.
INTERACTIVE_SQL: Final[str] = (
    "coalesce(is_interactive,"
    " TRY_CAST(TRY(json_extract_string(raw, '$.isInteractive')) AS BOOLEAN))"
)


@dataclass(frozen=True, slots=True)
class Code:
    code: int
    cls: SignInClass
    label: str
    shipped: SignInClass | None  # the class in the shipped file; None if added by config


def load_shipped(path: Path = CODES_FILE) -> dict[int, tuple[SignInClass, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[int, tuple[SignInClass, str]] = {}
    for cls, codes in (data.get("classes") or {}).items():
        if cls not in CLASSES or cls == "other":
            raise ValueError(f"{path.name}: unknown class {cls!r}")
        for code, label in (codes or {}).items():
            if int(code) in out:
                raise ValueError(f"{path.name}: code {code} is in two classes")
            out[int(code)] = (cast(SignInClass, cls), str(label))
    return out


def parse_overrides(raw: Mapping[str, str]) -> dict[int, SignInClass]:
    """`{"50074": "failed"}` -> {50074: "failed"}; a bad code or class is a config error."""
    out: dict[int, SignInClass] = {}
    for code, cls in raw.items():
        try:
            n = int(str(code).strip())
        except ValueError:
            raise ValueError(f"m365.signin_classes: {code!r} is not an error code") from None
        if cls not in CLASSES:
            raise ValueError(
                f"m365.signin_classes: {code} -> {cls!r}; use one of {', '.join(CLASSES)}"
            )
        out[n] = cls
    return out


class _Active:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._shipped = load_shipped()
        self._overrides: dict[int, SignInClass] = {}
        self._build()

    def _build(self) -> None:
        merged: dict[int, SignInClass] = {c: cls for c, (cls, _) in self._shipped.items()}
        merged.update(self._overrides)
        self.merged = merged
        self.macro = _macro(merged)
        self.version = hashlib.sha256(self.macro.encode()).hexdigest()[:12]

    def set_overrides(self, overrides: Mapping[int, SignInClass]) -> None:
        with self._lock:
            self._overrides = dict(overrides)
            self._build()

    def codes(self) -> list[Code]:
        out = []
        for code in sorted(set(self._shipped) | set(self._overrides)):
            shipped = self._shipped.get(code)
            label = shipped[1] if shipped else "Added on this install"
            out.append(Code(code, self.merged[code], label, shipped[0] if shipped else None))
        return out

    def adjusted(self) -> list[Code]:
        return [c for c in self.codes() if c.cls != c.shipped]


def _macro(merged: Mapping[int, SignInClass]) -> str:
    whens = []
    for cls in CLASSES:
        codes = sorted(c for c, k in merged.items() if k == cls)
        if codes:
            whens.append(f"WHEN c IN ({', '.join(str(c) for c in codes)}) THEN '{cls}'")
    return (
        f"CREATE OR REPLACE TEMP MACRO signin_class(c) AS CASE {' '.join(whens)} ELSE 'other' END"
    )


ACTIVE: Final[_Active] = _Active()


def set_overrides(overrides: Mapping[int, SignInClass]) -> None:
    """Set once at startup from `m365.signin_classes` (and again if that changes)."""
    ACTIVE.set_overrides(overrides)


def macro_sql() -> str:
    return ACTIVE.macro


def version() -> str:
    """Changes with the classes in force; a kept DuckDB instance is rebuilt when it does."""
    return ACTIVE.version


def class_sql(cls: SignInClass) -> str:
    """A failed sign-in of one class, as a WHERE condition on `events`."""
    return f"status_id = 2 AND signin_class({CODE_SQL}) = '{cls}'"


# A real failure in any authentication source: every failure outside Microsoft 365
# sign-ins, and a sign-in failure whose code is in the failed class.
REAL_FAILURE_SQL: Final[str] = (
    "status_id = 2 AND (template_id IS DISTINCT FROM 'm365_signin'"
    f" OR signin_class({CODE_SQL}) = 'failed')"
)
