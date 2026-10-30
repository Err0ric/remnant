"""Event table schema: flattened OCSF columns.

This is the single source of truth for the event schema (CLAUDE.md rule 9).
Templates, DuckDB views, the pySigma pipeline, and the UI column registry all
import from here. Changes are additive only: never rename or remove a column.

See docs/SPEC.md section 3.4.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import pyarrow as pa

OCSF_VERSION: Final[str] = "1.3.0"
SCHEMA_VERSION: Final[int] = 1


class ColumnType(StrEnum):
    STRING = "string"
    INT = "int"
    TIMESTAMPTZ = "timestamptz"
    BOOL = "bool"
    JSON = "json"  # stored as a JSON-encoded string


DUCKDB_TYPES: Final[dict[ColumnType, str]] = {
    ColumnType.STRING: "VARCHAR",
    ColumnType.INT: "BIGINT",
    ColumnType.TIMESTAMPTZ: "TIMESTAMP WITH TIME ZONE",
    ColumnType.BOOL: "BOOLEAN",
    ColumnType.JSON: "VARCHAR",
}


class ColumnGroup(StrEnum):
    IDENTITY = "identity"
    TIME = "time"
    CLASSIFICATION = "classification"
    OCSF = "ocsf"
    ESCAPE_HATCH = "escape_hatch"
    PARSE = "parse"
    GOVERNANCE = "governance"


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: ColumnType
    group: ColumnGroup
    description: str
    nullable: bool = True
    ocsf_path: str | None = None

    @property
    def duckdb_type(self) -> str:
        return DUCKDB_TYPES[self.type]


_S, _I, _T, _B, _J = (
    ColumnType.STRING,
    ColumnType.INT,
    ColumnType.TIMESTAMPTZ,
    ColumnType.BOOL,
    ColumnType.JSON,
)
_G = ColumnGroup

COLUMNS: Final[tuple[Column, ...]] = (
    # Identity
    Column(
        "event_id", _S, _G.IDENTITY, "UUIDv7 generated at ingest. The citation key.", nullable=False
    ),
    Column("source_id", _S, _G.IDENTITY, "Source this event came from.", nullable=False),
    Column("template_id", _S, _G.IDENTITY, "Template that parsed the event.", nullable=False),
    Column("template_version", _S, _G.IDENTITY, "Template version used.", nullable=False),
    # Time
    Column("time", _T, _G.TIME, "Event time, UTC.", ocsf_path="time"),
    Column("time_observed", _T, _G.TIME, "Ingest time, UTC.", nullable=False),
    # OCSF classification
    Column("class_uid", _I, _G.CLASSIFICATION, "OCSF event class.", ocsf_path="class_uid"),
    Column("category_uid", _I, _G.CLASSIFICATION, "OCSF category.", ocsf_path="category_uid"),
    Column("activity_id", _I, _G.CLASSIFICATION, "OCSF activity.", ocsf_path="activity_id"),
    Column("severity_id", _I, _G.CLASSIFICATION, "0 unknown .. 6 fatal.", ocsf_path="severity_id"),
    Column("status_id", _I, _G.CLASSIFICATION, "OCSF status.", ocsf_path="status_id"),
    Column("message", _S, _G.OCSF, "OCSF message.", ocsf_path="message"),
    # Actor
    Column("actor_user_name", _S, _G.OCSF, "Acting user.", ocsf_path="actor.user.name"),
    Column("actor_process_name", _S, _G.OCSF, "Acting process.", ocsf_path="actor.process.name"),
    Column("actor_process_pid", _I, _G.OCSF, "Acting process id.", ocsf_path="actor.process.pid"),
    # Source endpoint
    Column("src_endpoint_ip", _S, _G.OCSF, "Source IP.", ocsf_path="src_endpoint.ip"),
    Column("src_endpoint_port", _I, _G.OCSF, "Source port.", ocsf_path="src_endpoint.port"),
    Column("src_endpoint_hostname", _S, _G.OCSF, "Source host.", ocsf_path="src_endpoint.hostname"),
    # Destination endpoint
    Column("dst_endpoint_ip", _S, _G.OCSF, "Destination IP.", ocsf_path="dst_endpoint.ip"),
    Column("dst_endpoint_port", _I, _G.OCSF, "Destination port.", ocsf_path="dst_endpoint.port"),
    Column(
        "dst_endpoint_hostname", _S, _G.OCSF, "Destination host.", ocsf_path="dst_endpoint.hostname"
    ),
    # Reporting device
    Column("device_hostname", _S, _G.OCSF, "Reporting device host.", ocsf_path="device.hostname"),
    Column("device_ip", _S, _G.OCSF, "Reporting device IP.", ocsf_path="device.ip"),
    # What an action was on, and why it ended as it did (D121, F66): the app a consent or a
    # sign-in was for, a role or policy changed, the reason a result failed, and the id
    # Microsoft gives one operation across its logs.
    Column(
        "resource_name",
        _S,
        _G.OCSF,
        "Resource acted on: app, role, policy, file.",
        ocsf_path="resources.name",
    ),
    Column(
        "resource_uid", _S, _G.OCSF, "Its id (an app's application id).", ocsf_path="resources.uid"
    ),
    Column(
        "resource_type",
        _S,
        _G.OCSF,
        "Its kind (ServicePrincipal, Role, Policy).",
        ocsf_path="resources.type",
    ),
    Column(
        "status_detail",
        _S,
        _G.OCSF,
        "Why the result was what it was (failure reason).",
        ocsf_path="status_detail",
    ),
    Column(
        "privileges",
        _S,
        _G.OCSF,
        "Permissions requested or granted, space separated.",
        ocsf_path="privileges",
    ),
    Column(
        "metadata_correlation_uid",
        _S,
        _G.OCSF,
        "Id shared by one operation's records.",
        ocsf_path="metadata.correlation_uid",
    ),
    # Escape hatches
    Column(
        "unmapped", _J, _G.ESCAPE_HATCH, "Parsed fields with no OCSF target.", ocsf_path="unmapped"
    ),
    Column("envelope", _J, _G.ESCAPE_HATCH, "Syslog envelope fields and relay_hops."),
    Column("raw", _S, _G.ESCAPE_HATCH, "Original line, never modified.", nullable=False),
    Column(
        "raw_bytes_invalid",
        _B,
        _G.ESCAPE_HATCH,
        "True if non-UTF-8 bytes were replaced.",
        nullable=False,
    ),
    # Parse status
    Column("parse_status", _S, _G.PARSE, "ok | partial | envelope_only | failed", nullable=False),
    Column("parse_errors", _S, _G.PARSE, "Short reason when parse_status is not ok."),
    # Governance
    Column(
        "classification",
        _S,
        _G.GOVERNANCE,
        "local_only | cloud_allowed, copied from source.",
        nullable=False,
    ),
    Column("owner_id", _S, _G.GOVERNANCE, "Multi-user ready, constant in v1.", nullable=False),
)

COLUMN_NAMES: Final[tuple[str, ...]] = tuple(c.name for c in COLUMNS)
COLUMNS_BY_NAME: Final[dict[str, Column]] = {c.name: c for c in COLUMNS}

PARSE_STATUSES: Final[frozenset[str]] = frozenset({"ok", "partial", "envelope_only", "failed"})
CLASSIFICATIONS: Final[frozenset[str]] = frozenset({"local_only", "cloud_allowed"})


def get_column(name: str) -> Column:
    """Return a column by name or raise KeyError."""
    return COLUMNS_BY_NAME[name]


def duckdb_create_table_sql(table: str = "events") -> str:
    """CREATE TABLE statement for the event schema, used for empty-lake views and tests."""
    cols = ",\n  ".join(
        f'"{c.name}" {c.duckdb_type}{"" if c.nullable else " NOT NULL"}' for c in COLUMNS
    )
    return f'CREATE TABLE "{table}" (\n  {cols}\n)'


_ARROW_TYPES: Final[dict[ColumnType, pa.DataType]] = {
    ColumnType.STRING: pa.string(),
    ColumnType.INT: pa.int64(),
    ColumnType.TIMESTAMPTZ: pa.timestamp("us", tz="UTC"),
    ColumnType.BOOL: pa.bool_(),
    ColumnType.JSON: pa.string(),
}


def arrow_schema() -> pa.Schema:
    """Arrow schema for Parquet files in the lake, in column order."""
    return pa.schema([pa.field(c.name, _ARROW_TYPES[c.type], nullable=c.nullable) for c in COLUMNS])
