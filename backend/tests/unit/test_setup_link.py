"""The one-time setup link follows server.public_url when set (install finding task 4)."""

from pathlib import Path

from app.auth.service import AuthService
from app.core.config import AppConfig
from app.meta.db import MetaDB


def _auth(tmp_path: Path, **server: object) -> AuthService:
    config = AppConfig.model_validate(
        {"server": {"host": "0.0.0.0", **server}, "paths": {"data_dir": str(tmp_path)}}
    )
    return AuthService(config, MetaDB(tmp_path / "meta.db"))


def test_link_uses_public_url_when_set(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    url = auth.setup_url("siem.example.internal", 8080, "https://siem.example.internal/")
    assert url.startswith("https://siem.example.internal/setup#")


def test_link_falls_back_to_name_and_port(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    assert auth.setup_url("siem.example.internal", 8080).startswith(
        "https://siem.example.internal:8080/setup#"
    )
