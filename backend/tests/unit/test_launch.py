"""F50: the service says in one line when it cannot read its own install."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import launch


def _deny(blocked: set[Path]):  # type: ignore[no-untyped-def]  # a test double for os.access
    real = os.access

    def access(path: object, mode: int) -> bool:
        if Path(str(path)) in blocked:
            return False
        return real(path, mode)  # type: ignore[arg-type]  # same signature as os.access

    return access


def _install(tmp_path: Path) -> Path:
    root = tmp_path / "opt" / "remnant"
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "backend" / ".venv" / "bin").mkdir(parents=True)
    (root / "backend" / ".venv" / "bin" / "app-server").write_text("#!")
    (root / "frontend" / "dist" / "index.html").write_text("<html>")
    return root


def test_a_readable_install_passes(tmp_path: Path) -> None:
    root = _install(tmp_path)
    assert launch.unreadable([root]) == []


def test_an_owner_only_file_is_named_with_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _install(tmp_path)
    bad = root / "backend" / ".venv" / "bin" / "app-server"
    monkeypatch.setattr(launch.os, "access", _deny({bad}))
    found = launch.unreadable([root / "backend"])
    assert found == [bad]
    message = launch.message_for(found[0])
    assert message.startswith("error: user ")
    assert f"cannot read {bad}" in message
    assert f"chmod -R a+rX {root}" in message  # the checkout, not the one file
    assert "\n" not in message


def test_an_unlistable_folder_is_reported_once_and_not_walked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _install(tmp_path)
    dist = root / "frontend" / "dist"
    monkeypatch.setattr(launch.os, "access", _deny({dist}))
    assert launch.unreadable([root / "frontend"]) == [dist]
    assert launch.unreadable([dist]) == [dist]


def test_run_stops_with_the_line_and_no_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(launch, "check", lambda: "error: user remnant cannot read /x")
    with pytest.raises(SystemExit) as stop:
        launch.run()
    assert stop.value.code == 78
    assert capsys.readouterr().err.strip() == "error: user remnant cannot read /x"


def test_the_check_of_this_install_passes() -> None:
    assert launch.check() is None
