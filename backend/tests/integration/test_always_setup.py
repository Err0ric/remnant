"""No account, no access, on every bind (D245 amends ADR-0001 item 1; audit 2026-11 H1).

With the app bound to 127.0.0.1 behind a same-host reverse proxy and no accounts yet, a
request from the network arrived as the implicit administrator: nothing on a loopback
connection tells a proxy from the person at the machine. So the no-sign-in mode is gone.
The first administrator is always made with the one-time link, which the server log and
`app-admin setup-link` on the server give.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app import admin
from app.auth.setup import SETUP_TTL, SetupLink, link_host, notice
from app.auth.users import LOCAL_OWNED
from app.core.config import load_config
from app.main import create_app, print_setup_link
from app.meta.db import MetaDB

pytestmark = pytest.mark.real_auth

NAME = "siem.corp.example"
ACCOUNT = {"username": "alice", "password": "correct horse battery"}


def _env(tmp_path: Path, **env: str) -> dict[str, str]:
    return {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": "127.0.0.1", **env}


def _client(tmp_path: Path, **env: str) -> TestClient:
    config = load_config(Path("missing.yaml"), _env(tmp_path, **env))
    return TestClient(create_app(config), base_url="http://127.0.0.1:8080")


def _link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    for key, value in _env(tmp_path).items():
        monkeypatch.setenv(key, value)
    result = CliRunner().invoke(admin.app, ["setup-link"])
    return result.exit_code, result.output


def _token(text: str) -> str:
    return text.split("/setup#", 1)[1].split()[0]


def test_a_loopback_install_with_no_accounts_lets_nobody_in(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/auth/state").json()["mode"] == "setup"
        for headers in (
            {},  # the person at the machine, or nginx with a bare proxy_pass: the same request
            {"Host": "localhost:8080"},
            {"X-Forwarded-For": "192.0.2.50"},
        ):
            res = client.get("/api/sources", headers=headers)
            assert res.status_code == 403, res.text
            assert "setup_required" in res.text
            assert client.get("/api/users", headers=headers).status_code == 403
        made = client.post("/api/users", json={"username": "mallory", "role": "admin"})
        assert made.status_code == 403


def test_through_a_proxy_that_passes_the_public_name(tmp_path: Path) -> None:
    with _client(tmp_path, APP__SERVER__PUBLIC_NAMES=NAME) as client:
        via_proxy = {"Host": NAME, "X-Forwarded-For": "192.0.2.50"}
        assert client.get("/api/sources", headers=via_proxy).status_code == 403
        assert client.get("/api/auth/state", headers=via_proxy).json()["mode"] == "setup"


def test_the_command_on_the_server_gives_a_link_that_makes_the_administrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _client(tmp_path) as client:
        code, out = _link(tmp_path, monkeypatch)
        assert code == 0, out
        assert "http://127.0.0.1:8080/setup#" in out
        assert "ssh -L 8080:127.0.0.1:8080" in out  # how to open it from another computer
        first = _token(out)
        # A second link replaces the first.
        second = _token(_link(tmp_path, monkeypatch)[1])
        assert client.post("/api/setup", json={"token": first, **ACCOUNT}).status_code == 403
        made = client.post("/api/setup", json={"token": second, **ACCOUNT})
        assert made.status_code == 201, made.text
        assert client.get("/api/auth/state").json()["mode"] == "login"
        assert client.get("/api/sources").status_code == 200
        # Used once; and with an administrator there is no further link.
        again = TestClient(client.app, base_url="http://127.0.0.1:8080")
        body = {"token": second, "username": "bob", "password": ACCOUNT["password"]}
        assert again.post("/api/setup", json=body).status_code == 409
        code, out = _link(tmp_path, monkeypatch)
        assert code == 1 and "/setup#" not in out
        audit = client.get("/api/audit/events", params={"action": "setup.link_issued"}).json()
        assert len(audit) == 2 and audit[0]["detail"] == {"by": "app-admin"}


def test_the_link_expires_and_is_kept_only_as_a_hash(tmp_path: Path) -> None:
    meta = MetaDB(tmp_path / "meta.sqlite")
    now = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    token = SetupLink(meta).issue(now)
    with sqlite3.connect(tmp_path / "meta.sqlite") as con:
        stored = con.execute("SELECT digest FROM setup_link").fetchone()[0]
    assert token not in stored and len(stored) == 64
    other = SetupLink(meta)  # the running server: another object on the same file
    assert not other.consume("wrong", now)
    assert not other.consume(token, now + SETUP_TTL)
    late = SetupLink(meta).issue(now)
    assert other.consume(late, now + SETUP_TTL - timedelta(seconds=1))
    assert not other.consume(late, now)


def test_what_the_old_local_user_owned_goes_to_the_first_administrator(tmp_path: Path) -> None:
    """An install that ran without sign-in before the update: its saved searches and
    schedules were owned by `local`. They keep running until the administrator exists,
    and are that administrator's from then on."""
    with _client(tmp_path) as client:
        app = client.app
        at = "2026-11-01T00:00:00+00:00"
        with app.state.meta.connect() as con:  # type: ignore[attr-defined]
            con.execute(
                "INSERT INTO saved_searches (search_id, name, owner_id, visibility, sql,"
                " created_at, updated_at) VALUES ('s1', 'Failed sign-ins', 'local', 'private',"
                " 'SELECT 1', ?, ?)",
                (at, at),
            )
            con.execute(
                "INSERT INTO schedules (schedule_id, kind, target_id, name, owner_id, cron,"
                " target_sha256, created_at, updated_at) VALUES ('c1', 'search', 's1',"
                " 'Failed sign-ins hourly', 'local', '0 * * * *', 'x', ?, ?)",
                (at, at),
            )
            con.execute(
                "INSERT INTO dashboards (dashboard_id, name, owner_id, created_at, updated_at)"
                " VALUES ('mine-local', 'My dashboard', 'local', ?, ?)",
                (at, at),
            )
            con.execute(
                "INSERT INTO alert_items (item_id, kind, subject, title, owner_id, created_at)"
                " VALUES ('a1', 'schedule', 'c1', 'Failed sign-ins hourly', 'local', ?)",
                (at,),
            )
        schedules = app.state.schedules  # type: ignore[attr-defined]
        assert schedules._local_mode() is True  # still runs as before the update
        token = _token(app.state.auth.setup_url("127.0.0.1", 8080))  # type: ignore[attr-defined]
        made = client.post("/api/setup", json={"token": token, **ACCOUNT})
        assert made.status_code == 201, made.text
        admin_id = made.json()["user"]["user_id"]
        with app.state.meta.connect() as con:  # type: ignore[attr-defined]
            owners = {
                con.execute(f"SELECT owner_id FROM {table}").fetchone()[0]  # fixed names
                for table in LOCAL_OWNED
            }
        assert owners == {admin_id}
        assert schedules._local_mode() is False
        assert [s["name"] for s in client.get("/api/searches").json()] == ["Failed sign-ins"]
        created = client.get("/api/audit/events", params={"action": "setup.admin_created"}).json()
        assert created[0]["detail"]["taken_over"] == dict.fromkeys(LOCAL_OWNED, 1)


def test_the_notice_names_the_command_and_the_tunnel(tmp_path: Path) -> None:
    local = load_config(Path("missing.yaml"), _env(tmp_path))
    assert link_host(local, "host.example") == "127.0.0.1"
    text = " ".join(notice(local, "http://127.0.0.1:8080/setup#t"))
    assert "app-admin setup-link" in text and "ssh -L 8080:127.0.0.1:8080" in text
    network = load_config(
        Path("missing.yaml"), _env(tmp_path, APP__SERVER__HOST="0.0.0.0")
    )  # the bind under test
    assert link_host(network, "host.example") == "host.example"
    assert "ssh -L" not in " ".join(notice(network, "https://host.example:8080/setup#t"))
    proxied = load_config(
        Path("missing.yaml"), _env(tmp_path, APP__SERVER__PUBLIC_URL=f"https://{NAME}")
    )
    assert len(notice(proxied, f"https://{NAME}/setup#t")) == 3


def test_every_start_with_no_accounts_prints_a_working_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _client(tmp_path) as client:
        app = client.app
        config = load_config(Path("missing.yaml"), _env(tmp_path))
        print_setup_link(config, app.state.auth)  # type: ignore[attr-defined]
        out = capsys.readouterr().out
        assert "one-time link" in out and "http://127.0.0.1:8080/setup#" in out
        made = client.post("/api/setup", json={"token": _token(out), **ACCOUNT})
        assert made.status_code == 201, made.text
        print_setup_link(config, app.state.auth)  # type: ignore[attr-defined]
        assert capsys.readouterr().out == ""  # an administrator exists: no link


def test_the_tunnel_hint_names_the_address_the_server_listens_on(tmp_path: Path) -> None:
    v6 = load_config(Path("missing.yaml"), _env(tmp_path, APP__SERVER__HOST="::1"))
    assert link_host(v6, "host.example") == "[::1]"
    assert "ssh -L 8080:[::1]:8080" in " ".join(notice(v6, "http://[::1]:8080/setup#t"))


def test_a_link_through_the_proxy_needs_the_public_name_and_the_url(tmp_path: Path) -> None:
    """The guide's proxy setup (nginx passing Host): the link built from the public URL
    creates the administrator through the proxy when the public name is set too."""
    env = {"APP__SERVER__PUBLIC_NAMES": NAME, "APP__SERVER__PUBLIC_URL": f"https://{NAME}"}
    with _client(tmp_path, **env) as client:
        config = load_config(Path("missing.yaml"), _env(tmp_path, **env))
        url = client.app.state.auth.setup_url(  # type: ignore[attr-defined]
            link_host(config, "host.example"), 8080, config.server.public_url
        )
        assert url.startswith(f"https://{NAME}/setup#")
        via_proxy = {"Host": NAME, "Origin": f"https://{NAME}", "X-Forwarded-For": "192.0.2.50"}
        assert client.get("/api/auth/state", headers=via_proxy).json()["mode"] == "setup"
        made = client.post("/api/setup", json={"token": _token(url), **ACCOUNT}, headers=via_proxy)
        assert made.status_code == 201, made.text
