"""Compatibility field mapping for community Sigma rules (SPEC 4.6, D13, ADR-0006).

Sigma rules name fields the way the log source does (`TargetUserName`, `EventID`, `Image`).
Our events keep a few of those as OCSF columns and everything else in `unmapped`, whose
shape depends on the transport:

| Transport | Where an EventData field sits in `unmapped` |
|---|---|
| NXLog JSON | top level: `TargetUserName` |
| Winlogbeat | `winlog.event_data.TargetUserName` |
| Native .evtx | `Event.EventData.TargetUserName` |

So a field becomes one SQL expression that tries each place in turn, and a single compiled
rule works whichever way the events arrived. Every expression is text (VARCHAR), so the
backend can compare case-insensitively without casts failing at run time.

Field names come from rule files, which are untrusted: only names made of letters, digits,
`_`, `-`, and `.` are accepted; anything else refuses the rule.
"""

import re

from sigma.processing.pipeline import ProcessingPipeline

from app.core.errors import RuleRejectedError

_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
# Places a Windows EventData field can sit, by transport (see the table above).
_EVENTDATA_PATHS = ("$.{q}", "$.winlog.event_data.{q}", "$.Event.EventData.{q}")


def _json(path: str) -> str:
    return f"json_extract_string(unmapped, '{path}')"


def _coalesce(paths: list[str]) -> str:
    return "coalesce(" + ", ".join(_json(p) for p in paths) + ")"


def _column(name: str) -> str:
    return f'CAST("{name}" AS VARCHAR)'


# Fields with a known home of their own. Paths are fixed strings, never built from input.
FIELD_EXPRESSIONS: dict[str, str] = {
    "EventID": _coalesce(
        [
            '$."EventID"',
            "$.winlog.event_id",
            # EVTX: an EventID with Qualifiers is an object; its number is under "#text".
            # That path must come first, or the whole object would be read as the id.
            '$.Event.System.EventID."#text"',
            "$.Event.System.EventID",
            "$.event_id",
        ]
    ),
    "Channel": _coalesce(
        ['$."Channel"', "$.winlog.channel", "$.Event.System.Channel", "$.log_name"]
    ),
    "Provider_Name": _coalesce(
        [
            '$."SourceName"',
            "$.winlog.provider_name",
            '$.Event.System.Provider."#attributes".Name',
            "$.provider",
        ]
    ),
    "Computer": _column("device_hostname"),
    "ComputerName": _column("device_hostname"),
    "Hostname": _column("device_hostname"),
}


def field_expression(name: str) -> str:
    """The SQL text expression for a Sigma field name."""
    if name in FIELD_EXPRESSIONS:
        return FIELD_EXPRESSIONS[name]
    if not _SAFE_FIELD.fullmatch(name):
        raise RuleRejectedError(f"Unsupported field name in rule: {name[:60]!r}")
    quoted = '"' + name + '"'  # a JSON path key; the name holds no quote or backslash
    return _coalesce([p.format(q=quoted) for p in _EVENTDATA_PATHS])


def compat_pipeline() -> ProcessingPipeline:
    """The processing pipeline run before conversion. Field resolution happens in the
    backend through field_expression(); this is where rule-shape fixes for specific
    logsources will go (for example Security 4688 names for Sysmon process fields)."""
    return ProcessingPipeline(name="Sigma compatibility pipeline", priority=20, items=[])
