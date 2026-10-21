"""Parser template schema, version 1 (SPEC 4.1), with load-time validation.

Everything a template can say is checked here, before any line is parsed: mapping targets
must be real columns that templates are allowed to set, regexes must compile with named
groups, JSON roots and XML paths must be valid, and at least three tests must exist.
Server-managed columns (raw, classification, ids, parse status) can never be mapped.
"""

import re
from typing import Annotated, Any, Literal, get_args

import regex
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.core.ids import AUTO_PARSER
from app.core.schema import COLUMNS_BY_NAME
from app.ingest.envelope import SyslogEnvelopeConfig
from app.ingest.payload.delimited import CsvParser
from app.ingest.payload.jsonpayload import parse_root
from app.ingest.payload.kv import KvParser
from app.ingest.payload.regexpayload import compile_patterns
from app.ingest.payload.xmlpayload import XmlParser

TEMPLATE_ID = re.compile(r"[a-z][a-z0-9_]{1,63}")
SEMVER = re.compile(r"\d+\.\d+\.\d+")
# Set by the server, never by a template (CLAUDE.md rules 5 and 6).
SERVER_COLUMNS = frozenset(
    {
        "event_id",
        "source_id",
        "template_id",
        "template_version",
        "time_observed",
        "raw",
        "raw_bytes_invalid",
        "parse_status",
        "parse_errors",
        "classification",
        "owner_id",
        "envelope",
        "unmapped",
    }
)
# Class comes from mapping.class_uid / class_by so category_uid always follows it.
CLASS_COLUMNS = frozenset({"class_uid", "category_uid"})
OcsfId = Annotated[int, Field(ge=0, le=999_999)]
Scalar = str | int | float | bool | None
ENVELOPE_FIELDS = frozenset(
    {"timestamp", "hostname", "app_name", "procid", "msgid", "msg", "pri", "facility", "severity"}
)
TransformOp = Literal[
    "to_int",
    "to_lower",
    "to_upper",
    "strip",
    "split",
    "regex_extract",
    "map",
    "timestamp",
    "join",
    "replace",
    "pick",
]
Name = Annotated[str, StringConstraints(min_length=1, max_length=128)]
# "#" reaches the "#text" and "#attributes" keys the evtx library writes.
FieldRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_@$#.\-\[\]: ]{1,200}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _check_ref(ref: str) -> str:
    if ref.startswith("envelope.") and ref.removeprefix("envelope.") not in ENVELOPE_FIELDS:
        raise ValueError(f"unknown envelope field {ref.removeprefix('envelope.')}")
    return ref


def _compile(pattern: str | None, what: str) -> None:
    if pattern is None:
        return
    try:
        regex.compile(pattern)
    except regex.error as exc:
        raise ValueError(f"{what}: {exc}") from exc


def _scalars(value: object, what: str) -> None:
    """Defaults and value maps hold plain values only (no nested YAML structures)."""
    items = value.values() if isinstance(value, dict) else [value]
    for v in items:
        if v is not None and not isinstance(v, str | int | float | bool):
            raise ValueError(f"{what} values must be plain strings, numbers, or booleans")
        if isinstance(v, str) and len(v) > 2000:
            raise ValueError(f"{what} values are limited to 2000 characters")


EnvelopeDefault = Literal[
    "time", "device_hostname", "actor_process_name", "actor_process_pid", "message"
]


class EnvelopeSpec(_Strict):
    type: Literal["syslog", "none"]
    syslog: SyslogEnvelopeConfig = Field(default_factory=SyslogEnvelopeConfig)
    # The same source may arrive with or without a syslog header (file vs forwarder).
    optional: bool = False
    # Columns the header fills when the mapping leaves them empty. Windows forwarders put
    # the event provider in the tag, which is not a process, so those templates opt out.
    defaults: list[EnvelopeDefault] = Field(
        default_factory=lambda: list(get_args(EnvelopeDefault)), max_length=5
    )


class MatchSpec(_Strict):
    app_name: list[Name] = Field(default_factory=list, max_length=50)
    regex: str | None = Field(default=None, max_length=2000)
    min_confidence: float = Field(default=0.8, ge=0, le=1)

    @field_validator("regex")
    @classmethod
    def _regex(cls, value: str | None) -> str | None:
        _compile(value, "match.regex")
        return value


class MultilineSpec(_Strict):
    start: str | None = Field(default=None, max_length=500)

    @field_validator("start")
    @classmethod
    def _start(cls, value: str | None) -> str | None:
        _compile(value, "framing.multiline.start")
        return value


class FramingSpec(_Strict):
    # lines: newline-framed text files. evtx: Windows .evtx files, one frame per record,
    # rendered to JSON by the evtx library (that JSON is the event's raw).
    mode: Literal["lines", "evtx"] = "lines"
    multiline: MultilineSpec = Field(default_factory=MultilineSpec)
    max_len: int = Field(default=8192, ge=256, le=65536)


class KvSpec(_Strict):
    pair_sep: str = Field(default=" ", min_length=1, max_length=4)
    kv_sep: str = Field(default="=", min_length=1, max_length=4)
    quote: str | None = Field(default='"', min_length=1, max_length=1)


class CsvSpec(_Strict):
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    columns: list[Annotated[str, StringConstraints(max_length=128)]] = Field(
        min_length=1, max_length=500
    )
    quote: str = Field(default='"', min_length=1, max_length=1)
    trailing: Literal["partial", "ignore"] = "partial"


class JsonSpec(_Strict):
    root: str = Field(default="$", max_length=200)

    @field_validator("root")
    @classmethod
    def _root(cls, value: str) -> str:
        parse_root(value)
        return value


class XmlSpec(_Strict):
    fields: dict[Name, Annotated[str, StringConstraints(min_length=1, max_length=300)]] = Field(
        min_length=1, max_length=200
    )
    namespaces: dict[Name, Annotated[str, StringConstraints(max_length=300)]] = Field(
        default_factory=dict
    )

    @field_validator("fields")
    @classmethod
    def _simple_paths(cls, value: dict[str, str]) -> dict[str, str]:
        # Descendant (//) and parent (..) steps make ElementTree searches blow up on
        # deeply nested hostile XML; child steps and predicates cover event formats.
        for name, path in value.items():
            bare = re.sub(r"\{[^}]*\}", "", path)  # namespace URIs in {...} may hold //
            if "//" in bare.strip().lstrip("/") or ".." in bare:
                raise ValueError(f"xml field {name}: use child paths, not // or ..")
        return value


class RegexSpec(_Strict):
    patterns: list[Annotated[str, StringConstraints(min_length=1, max_length=4000)]] = Field(
        min_length=1, max_length=50
    )

    @field_validator("patterns")
    @classmethod
    def _compile(cls, value: list[str]) -> list[str]:
        compile_patterns(value)
        return value


class PayloadSpec(_Strict):
    format: Literal["regex", "kv", "csv", "cef", "leef", "json", "xml", "plain"]
    encoding: Literal["utf-8"] = "utf-8"
    regex: RegexSpec | None = None
    kv: KvSpec | None = None
    csv: CsvSpec | None = None
    json_: JsonSpec | None = Field(default=None, alias="json")
    cef: dict[str, Any] | None = None
    leef: dict[str, Any] | None = None
    xml: XmlSpec | None = None

    @model_validator(mode="after")
    def _block_for_format(self) -> "PayloadSpec":
        if self.format == "regex" and self.regex is None:
            raise ValueError("payload.format regex needs a payload.regex block")
        if self.format == "csv" and self.csv is None:
            raise ValueError("payload.format csv needs a payload.csv block with columns")
        if self.format == "xml":
            if self.xml is None:
                raise ValueError("payload.format xml needs a payload.xml block with fields")
            XmlParser(dict(self.xml.fields), dict(self.xml.namespaces))
        # Build the parsers now so a bad combination fails here, not at first use.
        if self.kv is not None:
            KvParser(self.kv.pair_sep, self.kv.kv_sep, self.kv.quote)
        if self.csv is not None:
            CsvParser(list(self.csv.columns), self.csv.delimiter, self.csv.quote, self.csv.trailing)
        return self


class Transform(_Strict):
    field: FieldRef
    op: TransformOp
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _args(self) -> "Transform":
        a = self.args
        if self.op == "split" and not isinstance(a.get("sep"), str):
            raise ValueError("split needs args.sep")
        if self.op == "regex_extract":
            try:
                compiled = regex.compile(str(a.get("pattern", "")))
            except regex.error as exc:
                raise ValueError(f"regex_extract pattern: {exc}") from exc
            group = a.get("group", 1)
            if isinstance(group, int) and not 0 <= group <= compiled.groups:
                raise ValueError(f"regex_extract group {group} is not in the pattern")
            if isinstance(group, str) and group not in compiled.groupindex:
                raise ValueError(f"regex_extract group {group!r} is not in the pattern")
            if not isinstance(group, int | str):
                raise ValueError("regex_extract group must be a number or a name")
        if self.op == "map":
            _scalars(a.get("values"), "map")
            _scalars(a.get("default"), "map default")
        if "into" in a and not isinstance(a["into"], str):
            raise ValueError("into must be a field name")
        if self.op == "map" and not isinstance(a.get("values"), dict):
            raise ValueError("map needs args.values")
        if "optional" in a and not isinstance(a["optional"], bool):
            raise ValueError("optional must be true or false")
        if self.op == "map" and a.get("optional") is True and "default" in a:
            raise ValueError("map takes a default or optional: true, not both")
        if self.op == "pick":
            choices = a.get("from")
            if not isinstance(choices, dict) or not choices or len(choices) > 20:
                raise ValueError("pick needs args.from, a map of value to field name")
            for ref in choices.values():
                if not isinstance(ref, str):
                    raise ValueError("pick from values must be field names")
                _check_ref(TypeAdapter(FieldRef).validate_python(ref))
            if not isinstance(a.get("into"), str):
                raise ValueError("pick needs args.into")
        if self.op == "timestamp":
            fmt = a.get("format")
            formats = fmt if isinstance(fmt, list) else [fmt]
            if not formats or not all(isinstance(f, str) and f for f in formats):
                raise ValueError(
                    "timestamp needs args.format: strptime, iso8601, bsd, epoch, epoch_ms, "
                    "epoch_auto, or a list of them tried in order"
                )
        if self.op == "join":
            others = a.get("with")
            if not isinstance(others, list) or not all(isinstance(o, str) for o in others):
                raise ValueError("join needs args.with, a list of field names")
            if not isinstance(a.get("into"), str):
                raise ValueError("join needs args.into")
        if self.op == "replace":
            try:
                regex.compile(str(a.get("pattern", "")))
            except regex.error as exc:
                raise ValueError(f"replace pattern: {exc}") from exc
            if not isinstance(a.get("with", ""), str):
                raise ValueError("replace with must be text")
        return self


class FieldMap(_Strict):
    # One field, or a list: the first one with a value wins.
    from_: FieldRef | list[FieldRef] | None = Field(default=None, alias="from")
    map: dict[str, Any] | None = None
    default: Any = None

    @model_validator(mode="after")
    def _source(self) -> "FieldMap":
        if self.from_ is None and self.default is None:
            raise ValueError("a mapped field needs from or default")
        for ref in self.sources:
            _check_ref(ref)
        _scalars(self.default, "default")
        if self.map is not None:
            _scalars(self.map, "map")
        return self

    @property
    def sources(self) -> list[str]:
        if self.from_ is None:
            return []
        return [self.from_] if isinstance(self.from_, str) else list(self.from_)


class ActorRefs(_Strict):
    """Where the acting user is, by the table entry's `actor` role. Windows logon events
    name the user logging on in Target*; account, group, and process events name the
    user who did it in Subject*."""

    subject: list[FieldRef] = Field(min_length=1, max_length=8)
    target: list[FieldRef] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _refs(self) -> "ActorRefs":
        for ref in [*self.subject, *self.target]:
            _check_ref(ref)
        return self


class LookupSpec(_Strict):
    """Class, activity, status, and severity from a shared table (windows_eventid)."""

    field: FieldRef
    table: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    actor: ActorRefs | None = None

    @field_validator("field")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _check_ref(value)


class ClassBy(_Strict):
    field: FieldRef
    values: dict[str, OcsfId] = Field(max_length=1000)

    @field_validator("field")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _check_ref(value)


class SeverityMap(_Strict):
    from_: FieldRef = Field(alias="from")
    map: dict[str, Literal[0, 1, 2, 3, 4, 5, 6, 99]] = Field(default_factory=dict)

    @field_validator("from_")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _check_ref(value)


class MappingSpec(_Strict):
    class_uid: OcsfId
    class_by: ClassBy | None = None
    lookup: LookupSpec | None = None
    fields: dict[str, FieldMap] = Field(default_factory=dict)
    severity: SeverityMap | None = None

    @field_validator("fields")
    @classmethod
    def _columns(cls, value: dict[str, FieldMap]) -> dict[str, FieldMap]:
        for column in value:
            if column not in COLUMNS_BY_NAME:
                raise ValueError(f"{column} is not a column (see core/schema.py)")
            if column in SERVER_COLUMNS:
                raise ValueError(f"{column} is set by the server and cannot be mapped")
            if column in CLASS_COLUMNS:
                raise ValueError(f"set {column} with mapping.class_uid or class_by")
        return value

    @model_validator(mode="after")
    def _one_actor_source(self) -> "MappingSpec":
        if self.lookup and self.lookup.actor and "actor_user_name" in self.fields:
            raise ValueError("map actor_user_name in fields or in lookup.actor, not both")
        return self


class TestExpect(_Strict):
    parse_status: Literal["ok", "partial", "envelope_only", "failed"] = "ok"
    class_uid: int | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class TemplateTest(_Strict):
    name: Name
    input: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    expect: TestExpect


# "*" in a declared service or category: any value (the runner still narrows Windows rules
# to their channel and event ids, and refuses services it cannot narrow).
SigmaSlug = Annotated[str, StringConstraints(pattern=r"^([a-z0-9][a-z0-9_\-]{0,63}|\*)$")]


class SigmaLogSource(_Strict):
    """One Sigma logsource this template's events can satisfy (ADR-0006 row 2)."""

    product: SigmaSlug | None = None
    service: SigmaSlug | None = None
    category: SigmaSlug | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "SigmaLogSource":
        if self.product is None and self.service is None and self.category is None:
            raise ValueError("a Sigma logsource needs product, service, or category")
        if self.product == "*":
            raise ValueError("product cannot be *; name the product")
        return self


class SigmaSpec(_Strict):
    logsource: list[SigmaLogSource] = Field(default_factory=list, max_length=100)


class Template(_Strict):
    schema_version: Literal[1]
    id: str
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    version: str
    author: Annotated[str, StringConstraints(max_length=120)] = ""
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    # SPEC 3.6: from the OCSF class the template mostly produces; drives suggested groups.
    # Empty means no suggestion (for example a generic template).
    category: Literal["", "identity", "network", "dns", "system", "application", "findings"] = ""
    # Product family for optional vendor groups (paloalto, windows, linux, ...).
    vendor: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{0,32}$")] = ""
    classification_default: Literal["local_only", "cloud_allowed"] = "local_only"
    # Sigma rules run only on sources whose template declares a matching logsource.
    sigma: SigmaSpec = Field(default_factory=SigmaSpec)
    envelope: EnvelopeSpec
    match: MatchSpec = Field(default_factory=MatchSpec)
    framing: FramingSpec = Field(default_factory=FramingSpec)
    payload: PayloadSpec
    transforms: list[Transform] = Field(default_factory=list, max_length=100)
    mapping: MappingSpec
    tests: list[TemplateTest] = Field(min_length=3, max_length=100)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not TEMPLATE_ID.fullmatch(value):
            raise ValueError("id must be snake_case: [a-z][a-z0-9_]{1,63}")
        if value == AUTO_PARSER:
            raise ValueError(f"id '{AUTO_PARSER}' is reserved for the Automatic parser")
        return value

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not SEMVER.fullmatch(value):
            raise ValueError("version must be semver, like 1.0.0")
        return value

    @model_validator(mode="after")
    def _expectations_are_columns(self) -> "Template":
        for t in self.tests:
            for column in t.expect.fields:
                if column not in COLUMNS_BY_NAME:
                    raise ValueError(f"test {t.name!r} expects unknown column {column}")
        return self
