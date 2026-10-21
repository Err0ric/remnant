import re

import pytest

from app.core.schema import (
    COLUMN_NAMES,
    COLUMNS,
    DUCKDB_TYPES,
    ColumnType,
    duckdb_create_table_sql,
    get_column,
)

REQUIRED = {
    "event_id",
    "source_id",
    "template_id",
    "template_version",
    "time",
    "time_observed",
    "class_uid",
    "severity_id",
    "status_id",
    "message",
    "unmapped",
    "envelope",
    "raw",
    "raw_bytes_invalid",
    "parse_status",
    "parse_errors",
    "classification",
    "owner_id",
}


def test_column_names_unique() -> None:
    assert len(COLUMN_NAMES) == len(set(COLUMN_NAMES))


def test_required_columns_present() -> None:
    missing = REQUIRED - set(COLUMN_NAMES)
    assert not missing, f"missing columns: {missing}"


def test_event_id_is_first_and_required() -> None:
    assert COLUMNS[0].name == "event_id"
    assert COLUMNS[0].nullable is False


@pytest.mark.parametrize("name", ["raw", "classification", "parse_status", "owner_id"])
def test_governance_and_raw_columns_not_nullable(name: str) -> None:
    assert get_column(name).nullable is False


def test_names_are_snake_case() -> None:
    for name in COLUMN_NAMES:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


def test_every_type_maps_to_duckdb() -> None:
    assert set(DUCKDB_TYPES) == set(ColumnType)


def test_create_table_sql_mentions_every_column() -> None:
    sql = duckdb_create_table_sql()
    for name in COLUMN_NAMES:
        assert f'"{name}"' in sql
