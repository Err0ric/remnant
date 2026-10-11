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
