"""Single sign-on end to end against an in-process provider (ADR-0013)."""

import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppConfig, load_config
from app.main import create_app
from tests.fake_idp import CLIENT_ID, ISSUER, SECRET, FakeIdp

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal:8080"


def server(tmp_path: Path, idp: FakeIdp | None, **sso: str) -> TestClient:
    env = {
        "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
        "APP__SERVER__HOST": "0.0.0.0",
        "APP__SERVER__PUBLIC_NAMES": "siem.example.internal",
    }
    if idp is not None:
        env |= {
            "APP__SSO__ENABLED": "true",
            "APP__SSO__ISSUER": ISSUER,
            "APP__SSO__CLIENT_ID": CLIENT_ID,
            "APP__SSO__CLIENT_SECRET": SECRET,
        }
        env |= {f"APP__SSO__{k.upper()}": v for k, v in sso.items()}
    config = load_config(Path("missing.yaml"), env)
    c = TestClient(create_app(config, sso_http=idp.client if idp else None), base_url=BASE)
    token = c.app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]  # type: ignore[attr-defined]
    res = c.post("/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW})
    assert res.status_code == 201, res.text
    c.headers["X-CSRF-Token"] = res.json()["csrf_token"]
    return c


def invite(c: TestClient, username: str, role: str = "analyst") -> str:
    res = c.post("/api/users", json={"username": username, "role": role})
    assert res.status_code == 201, res.text
    return str(res.json()["invite_token"])


def browser(c: TestClient) -> TestClient:
    return TestClient(c.app, base_url=BASE)


def sso_sign_in(
    b: TestClient, idp: FakeIdp, sub: str, link: str | None = None, **claims: object
) -> str:
    """Run the whole browser flow; returns where the callback redirected."""
    res = b.post("/api/auth/sso/start", json={"link_token": link} if link else {})
    assert res.status_code == 200, res.text
    state, code = idp.approve(res.json()["url"], sub, **claims)
    back = b.get(
        "/api/auth/sso/callback", params={"state": state, "code": code}, follow_redirects=False
    )
    assert back.status_code == 303
    return str(back.headers["location"])


def refusal(location: str) -> str | None:
    return parse_qs(urlparse(location).query).get("sso", [None])[0]


def audit(tmp_path: Path) -> list[tuple[str, str]]:
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    return [(r[0], r[1]) for r in db.execute("SELECT action, outcome FROM audit_log")]


@pytest.fixture
def idp() -> FakeIdp:
    return FakeIdp()


def test_invite_binds_the_identity_then_it_signs_in(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    link = invite(c, "jordan")
    b = browser(c)
    assert sso_sign_in(b, idp, "sub-jordan", link) == "/"
    me = b.get("/api/auth/state").json()
    assert me["user"]["username"] == "jordan"
    assert me["sso"] == {"label": "Microsoft", "passwords_admins_only": True}
    # Later sign-ins find the account by issuer + subject alone.
    again = browser(c)
    assert sso_sign_in(again, idp, "sub-jordan") == "/"
    assert again.get("/api/auth/state").json()["user"]["username"] == "jordan"
    users = {u["username"]: u for u in c.get("/api/users").json()}
    assert users["jordan"]["sso"] is True and users["admin"]["sso"] is False
    actions = audit(tmp_path)
    assert ("user.sso_linked", "success") in actions
    assert actions.count(("auth.login", "success")) >= 2


def test_cookies(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    link = invite(c, "jordan")
    b = browser(c)
    res = b.post("/api/auth/sso/start", json={"link_token": link})
    flow = res.headers["set-cookie"].lower()
    for part in ("sso_flow=", "httponly", "secure", "samesite=lax", "path=/api/auth/sso/callback"):
        assert part in flow
    state, code = idp.approve(res.json()["url"], "sub-jordan")
    back = b.get(
        "/api/auth/sso/callback", params={"state": state, "code": code}, follow_redirects=False
    )
    cookies = " ".join(back.headers.get_list("set-cookie")).lower()
    assert "samesite=strict" in cookies and "httponly" in cookies


def test_used_link_cannot_start_again(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    link = invite(c, "jordan")
    sso_sign_in(browser(c), idp, "sub-jordan", link)
    res = browser(c).post("/api/auth/sso/start", json={"link_token": link})
    assert res.status_code == 403 and res.json()["code"] == "link_invalid"


def test_abandoned_or_failed_sign_in_leaves_the_invite_usable(tmp_path: Path, idp: FakeIdp) -> None:
    """Starting single sign-on with a link only checks it; a flow that never comes back, or
    a start without the code (lost to a forward-auth redirect), does not spend it."""
    c = server(tmp_path, idp)
    link = invite(c, "jordan")
    assert browser(c).post("/api/auth/sso/start", json={"link_token": link}).status_code == 200
    assert browser(c).post("/api/auth/sso/start", json={}).status_code == 200
    assert sso_sign_in(browser(c), idp, "sub-jordan", link) == "/"


def test_identity_without_an_invite_is_refused(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    b = browser(c)
    assert refusal(sso_sign_in(b, idp, "sub-stranger")) == "not_invited"
    assert b.get("/api/auth/state").json()["user"] is None
    assert ("auth.sso_refused", "failure") in audit(tmp_path)


def test_one_identity_cannot_bind_two_accounts(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    sso_sign_in(browser(c), idp, "sub-jordan", invite(c, "jordan"))
    assert refusal(sso_sign_in(browser(c), idp, "sub-jordan", invite(c, "sam"))) == (
        "already_linked"
    )


def test_disabled_account_is_refused(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    sso_sign_in(browser(c), idp, "sub-jordan", invite(c, "jordan"))
    user_id = next(u["user_id"] for u in c.get("/api/users").json() if u["username"] == "jordan")
    assert c.patch(f"/api/users/{user_id}", json={"disabled": True}).status_code == 200
    assert refusal(sso_sign_in(browser(c), idp, "sub-jordan")) == "disabled"


def test_required_group_checked_every_sign_in(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp, required_groups="g-siem")
    link = invite(c, "jordan")
    assert refusal(sso_sign_in(browser(c), idp, "sub-jordan", link, groups=["g-x"])) == (
        "not_in_group"
    )
    assert sso_sign_in(browser(c), idp, "sub-jordan", link, groups=["g-x", "g-siem"]) == "/"
    # Removed from the group in Entra: the account still exists here, but sign-in stops.
    assert refusal(sso_sign_in(browser(c), idp, "sub-jordan", groups=["g-x"])) == "not_in_group"
    idp.override = {"_claim_names": {"groups": "src1"}}
    assert refusal(sso_sign_in(browser(c), idp, "sub-jordan")) == "too_many_groups"


def test_provider_error_and_missing_flow_cookie(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    b = browser(c)
    res = b.post("/api/auth/sso/start", json={})
    state, _ = idp.approve(res.json()["url"], "sub-1")
    back = b.get(
        "/api/auth/sso/callback",
        params={"state": state, "error": "access_denied", "error_description": "<script>"},
        follow_redirects=False,
    )
    assert refusal(back.headers["location"]) == "denied"
    assert "script" not in back.headers["location"]

    res = b.post("/api/auth/sso/start", json={})
    state, code = idp.approve(res.json()["url"], "sub-1")
    other = browser(c)  # a different browser holding the callback URL
    back = other.get(
        "/api/auth/sso/callback", params={"state": state, "code": code}, follow_redirects=False
    )
    assert refusal(back.headers["location"]) == "invalid"


def test_passwords_limited_to_admins_when_sso_is_on(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    analyst_link = invite(c, "jordan")
    res = c.post("/api/account/password", json={"token": analyst_link, "password": USER_PW})
    assert res.status_code == 403 and res.json()["code"] == "sso_required"
    # The refused password attempt did not use the link up.
    assert sso_sign_in(browser(c), idp, "sub-jordan", analyst_link) == "/"

    admin_link = invite(c, "second_admin", role="admin")
    res = c.post("/api/account/password", json={"token": admin_link, "password": USER_PW})
    assert res.status_code == 204
    res = browser(c).post("/api/auth/login", json={"username": "second_admin", "password": USER_PW})
    assert res.status_code == 200


def _sso_config(tmp_path: Path) -> AppConfig:
    return load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__SERVER__HOST": "0.0.0.0",
            "APP__SERVER__PUBLIC_NAMES": "siem.example.internal",
            "APP__SSO__ENABLED": "true",
            "APP__SSO__ISSUER": ISSUER,
            "APP__SSO__CLIENT_ID": CLIENT_ID,
            "APP__SSO__CLIENT_SECRET": SECRET,
        },
    )


def test_analyst_password_refused_after_sso_turned_on(tmp_path: Path, idp: FakeIdp) -> None:
    plain = server(tmp_path, None)
    link = invite(plain, "jordan")
    assert (
        plain.post("/api/account/password", json={"token": link, "password": USER_PW}).status_code
        == 204
    )
    cli = browser(plain).post(
        "/api/auth/login", json={"username": "jordan", "password": USER_PW, "client": "cli"}
    )
    assert cli.status_code == 200
    old_token = cli.json()["token"]

    b = TestClient(create_app(_sso_config(tmp_path), sso_http=idp.client), base_url=BASE)
    # The token from before SSO was turned on no longer works.
    assert (
        b.get("/api/searches", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    )
    assert ("auth.sessions_ended", "success") in audit(tmp_path)
    # A right password and a wrong one get the same answer, so neither is confirmed.
    right = b.post(
        "/api/auth/login", json={"username": "jordan", "password": USER_PW, "client": "cli"}
    )
    wrong = b.post(
        "/api/auth/login", json={"username": "jordan", "password": "not it at all", "client": "cli"}
    )
    assert right.status_code == wrong.status_code == 401
    assert right.json() == wrong.json()
    assert "Microsoft" in right.json()["detail"]
    res = b.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert res.status_code == 200


def test_one_link_cannot_bind_two_identities(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    link = invite(c, "jordan")
    first, second = browser(c), browser(c)
    started = [b.post("/api/auth/sso/start", json={"link_token": link}) for b in (first, second)]
    flows = [
        idp.approve(r.json()["url"], sub)
        for r, sub in zip(started, ("sub-a", "sub-b"), strict=True)
    ]
    outcomes = [
        b.get(
            "/api/auth/sso/callback", params={"state": s, "code": code}, follow_redirects=False
        ).headers["location"]
        for b, (s, code) in zip((first, second), flows, strict=True)
    ]
    assert outcomes[0] == "/" and refusal(outcomes[1]) == "expired"
    assert second.get("/api/auth/state").json()["user"] is None


def test_start_is_rate_limited_and_refusals_audit_is_capped(tmp_path: Path, idp: FakeIdp) -> None:
    from app.auth import sso

    c = server(tmp_path, idp)
    b = browser(c)
    codes = [
        b.post("/api/auth/sso/start", json={}).status_code for _ in range(sso.STARTS_PER_WINDOW + 5)
    ]
    assert codes[: sso.STARTS_PER_WINDOW] == [200] * sso.STARTS_PER_WINDOW
    assert set(codes[sso.STARTS_PER_WINDOW :]) == {429}
    before = audit(tmp_path).count(("auth.sso_refused", "failure"))
    for _ in range(sso.REFUSALS_AUDITED_PER_WINDOW + 20):
        b.get("/api/auth/sso/callback", params={"error": "access_denied"}, follow_redirects=False)
    after = audit(tmp_path).count(("auth.sso_refused", "failure"))
    assert after - before == sso.REFUSALS_AUDITED_PER_WINDOW


def test_sso_only_account_is_not_shown_as_pending(tmp_path: Path, idp: FakeIdp) -> None:
    c = server(tmp_path, idp)
    sso_sign_in(browser(c), idp, "sub-jordan", invite(c, "jordan"))
    jordan = next(u for u in c.get("/api/users").json() if u["username"] == "jordan")
    assert jordan["pending"] is False and jordan["sso"] is True


def test_sso_off_by_default(tmp_path: Path) -> None:
    c = server(tmp_path, None)
    assert browser(c).get("/api/auth/state").json()["sso"] is None
    res = browser(c).post("/api/auth/sso/start", json={})
    assert res.status_code == 400 and res.json()["code"] == "sso_refused"
    back = browser(c).get(
        "/api/auth/sso/callback", params={"state": "x", "code": "y"}, follow_redirects=False
    )
    assert refusal(back.headers["location"]) == "off"


def test_secret_never_returned_or_logged(
    tmp_path: Path, idp: FakeIdp, capsys: pytest.CaptureFixture[str]
) -> None:
    c = server(tmp_path, idp)
    sso_sign_in(browser(c), idp, "sub-jordan", invite(c, "jordan"))
    sso_sign_in(browser(c), idp, "sub-stranger")
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    assert not any(SECRET in str(r) for r in db.execute("SELECT * FROM audit_log"))


def test_authelia_style_groups_from_userinfo(tmp_path: Path, idp: FakeIdp) -> None:
    """Authelia keeps groups out of the ID token by default and expects HTTP Basic."""
    idp.auth_methods = ["client_secret_basic"]
    idp.userinfo_only = {"groups", "preferred_username"}
    c = server(tmp_path, idp, required_groups="siem-users", extra_scopes="groups")
    link = invite(c, "jordan")
    assert refusal(sso_sign_in(browser(c), idp, "sub-j", link, groups=["other"])) == (
        "not_in_group"
    )
    b = browser(c)
    assert sso_sign_in(b, idp, "sub-j", link, groups=["siem-users"]) == "/"
    assert b.get("/api/auth/state").json()["user"]["username"] == "jordan"


def test_settings_page_shows_the_setup_and_tests_it(tmp_path: Path, idp: FakeIdp) -> None:
    """F64: status, issuer, client id, redirect URI, and who is bound; never the secret."""
    c = server(tmp_path, idp)
    link = invite(c, "jordan")
    assert sso_sign_in(browser(c), idp, "sub-jordan", link) == "/"
    res = c.get("/api/settings/sso")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "on" and body["problem"] is None
    assert body["issuer"] == ISSUER and body["client_id"] == CLIENT_ID
    assert body["redirect_uri"].endswith("/api/auth/sso/callback")
    assert [b["username"] for b in body["bound"]] == ["jordan"]
    assert SECRET not in res.text
    test = c.post("/api/settings/sso/test").json()
    assert test["ok"] is True and SECRET not in str(test)
    assert ("sso.test", "success") in audit(tmp_path)
