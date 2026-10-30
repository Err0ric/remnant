from pathlib import Path

from fastapi.testclient import TestClient

from app.core.branding import PRODUCT_NAME
from app.core.schema import COLUMN_NAMES
from app.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    assert client.get("/api/health").json() == {"status": "ok"}


def test_meta_serves_product_name_from_constant() -> None:
    client = TestClient(create_app())
    body = client.get("/api/meta").json()
    assert body["product_name"] == PRODUCT_NAME
    assert body["ocsf_version"]
    assert body["environment_label"] is None


def test_meta_serves_environment_label(tmp_path: Path) -> None:
    import pytest
    from pydantic import ValidationError

    from app.core.config import AppConfig, PathsConfig, ServerConfig

    config = AppConfig(
        server=ServerConfig(environment_label="Lab"), paths=PathsConfig(data_dir=tmp_path)
    )
    assert TestClient(create_app(config)).get("/api/meta").json()["environment_label"] == "Lab"
    assert ServerConfig(environment_label="").environment_label is None
    with pytest.raises(ValidationError):
        ServerConfig(environment_label="<script>")


def test_schema_columns_match_schema_module() -> None:
    client = TestClient(create_app())
    names = [c["name"] for c in client.get("/api/schema/columns").json()]
    assert tuple(names) == COLUMN_NAMES


def test_web_ui_routes_fall_back_to_index(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.core.config import load_config
    from app.main import create_app

    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<div id=root></div>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__STATIC_DIR": str(web)},
    )
    c = TestClient(create_app(config))
    assert c.get("/setup").text == "<div id=root></div>"
    assert c.get("/search/anything").status_code == 200
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/api/nope").status_code == 404
    assert "root" not in c.get("/api/nope").text


def test_install_name_is_set_by_admins_and_shown_only_when_signed_in(tmp_path: Path) -> None:
    import sqlite3

    from tests.integration.test_schedules import make_lab

    lab = make_lab(tmp_path)
    assert lab["admin"].get("/api/install").json() == {"name": ""}
    res = lab["admin"].put("/api/install", json={"name": "  Example   SOC "}, headers=lab["h"])
    assert res.status_code == 200 and res.json() == {"name": "Example SOC"}
    assert lab["ana"].get("/api/install").json() == {"name": "Example SOC"}
    assert lab["ana"].put("/api/install", json={"name": "x"}).status_code == 403
    bad = lab["admin"].put("/api/install", json={"name": "<b>x</b>"}, headers=lab["h"])
    assert bad.status_code == 422
    # Not on the unauthenticated meta: it may name the organization.
    assert "Example SOC" not in TestClient(lab["app"]).get("/api/meta").text
    assert TestClient(lab["app"]).get("/api/install").status_code == 401
    with sqlite3.connect(lab["db"]) as db:
        (detail,) = db.execute(
            "SELECT detail FROM audit_log WHERE action = 'install.update'"
        ).fetchone()
    assert "Example SOC" in detail
