"""Owner, 2026-11-03: a page failed 0.3 s after the today build swapped its files. A query
whose listed file vanished is planned again, once; any other failure is not retried."""

from pathlib import Path
from typing import Any

import pytest

from app.core.config import load_config
from app.core.errors import QueryFailedError
from app.engine.duckdb import QueryScope
from app.main import create_app


def _failure(message: str, kind: str) -> QueryFailedError:
    exc = QueryFailedError(message)
    exc.engine_error = kind
    return exc


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    app = create_app(load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path)}))
    return app.state.engine


def test_a_vanished_file_is_read_again_once(engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    real, calls = engine._execute, []

    def flaky(*a: Any, **k: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise _failure(
                'IO Error: No files found that match the pattern "<lake>/x"', "IOException"
            )
        return real(*a, **k)

    monkeypatch.setattr(engine, "_execute", flaky)
    assert engine.run("SELECT 1 AS one", QueryScope(None)).rows == [[1]]
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ('IO Error: No files found that match the pattern "<lake>/x"', "IOException"),
        ("Conversion Error: Could not convert", "ConversionException"),
    ],
)
def test_other_failures_and_a_second_vanish_are_raised(
    engine: Any, monkeypatch: pytest.MonkeyPatch, message: str, kind: str
) -> None:
    calls = []

    def always(*a: Any, **k: Any) -> Any:
        calls.append(1)
        raise _failure(message, kind)

    monkeypatch.setattr(engine, "_execute", always)
    with pytest.raises(QueryFailedError):
        engine.run("SELECT 1", QueryScope(None))
    assert len(calls) == (2 if kind == "IOException" else 1)
