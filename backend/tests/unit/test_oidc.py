"""OIDC protocol checks (ADR-0013 rows 1, 3, 10, 11) against an in-process provider."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from app.auth.oidc import OidcClient
from app.core.config import SsoConfig
from app.core.errors import SsoRefusedError
from tests.fake_idp import CLIENT_ID, ISSUER, SECRET, FakeIdp

REDIRECT = "https://siem.example.internal:8080/api/auth/sso/callback"


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def idp() -> FakeIdp:
    return FakeIdp()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(idp: FakeIdp, clock: Clock) -> Iterator[OidcClient]:
    config = SsoConfig(enabled=True, issuer=ISSUER, client_id=CLIENT_ID, client_secret=SECRET)
    yield OidcClient(config, REDIRECT, clock, http=idp.client)


def test_round_trip_with_pkce_state_and_nonce(idp: FakeIdp, client: OidcClient) -> None:
    url, cookie = client.begin(link_token="invite-123")
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["scope"] == ["openid profile"]
    state, code = idp.approve(url, "sub-jordan", preferred_username="jordan@corp.example")
    identity, link = client.finish(state, code, cookie)
    assert (identity.issuer, identity.subject) == (ISSUER, "sub-jordan")
    assert identity.name == "jordan@corp.example"
    assert identity.groups == ()
    assert link == "invite-123"
    # The secret goes only to the token endpoint, in the form body.
    assert idp.token_requests[0]["client_secret"] == [SECRET]
    assert SECRET not in url


def test_flow_is_single_use_and_bound_to_the_browser(idp: FakeIdp, client: OidcClient) -> None:
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    with pytest.raises(SsoRefusedError) as wrong:
        client.finish(state, code, "another-browser")
    assert wrong.value.code == "invalid"
    # The failed attempt used the flow up: it cannot be retried with the right cookie either.
    with pytest.raises(SsoRefusedError) as reused:
        client.finish(state, code, cookie)
    assert reused.value.code == "expired"


def test_flow_expires(idp: FakeIdp, client: OidcClient, clock: Clock) -> None:
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    clock.now += timedelta(minutes=11)
    with pytest.raises(SsoRefusedError) as exc:
        client.finish(state, code, cookie)
    assert exc.value.code == "expired"


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "https://login.example.test/other-tenant/v2.0"},
        {"aud": "someone-else"},
        {"nonce": "replayed"},
        {"exp": 1_000_000_000, "iat": 999_999_000, "nbf": 999_999_000},
        {"azp": "someone-else"},
    ],
    ids=["issuer", "audience", "nonce", "expired", "azp"],
)
def test_token_checks(idp: FakeIdp, client: OidcClient, override: dict[str, object]) -> None:
    idp.override = override
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    with pytest.raises(SsoRefusedError) as exc:
        client.finish(state, code, cookie)
    assert exc.value.code == "invalid"


def test_signature_from_another_key_is_refused(idp: FakeIdp, client: OidcClient) -> None:
    idp.sign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    with pytest.raises(SsoRefusedError) as exc:
        client.finish(state, code, cookie)
    assert exc.value.code == "invalid"


def test_groups_claim_and_overage(idp: FakeIdp, client: OidcClient) -> None:
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1", groups=["g-siem", "g-other"])
    identity, _ = client.finish(state, code, cookie)
    assert identity.groups == ("g-siem", "g-other")

    idp.override = {"_claim_names": {"groups": "src1"}}
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    identity, _ = client.finish(state, code, cookie)
    assert identity.groups is None


def test_discovery_for_another_issuer_is_refused(idp: FakeIdp, client: OidcClient) -> None:
    idp.discovery_issuer = "https://evil.example.test/v2.0"
    with pytest.raises(SsoRefusedError) as exc:
        client.begin()
    assert exc.value.code == "unavailable"


@pytest.mark.parametrize(
    "issuer",
    [
        "https://login.microsoftonline.com/common/v2.0",
        "https://login.microsoftonline.com/organizations/v2.0",
        "https://login.microsoftonline.com/consumers/v2.0",
        "http://login.microsoftonline.com/1111/v2.0",
    ],
)
def test_config_refuses_multi_tenant_or_plain_http(issuer: str) -> None:
    with pytest.raises(ValidationError) as exc:
        SsoConfig(enabled=True, issuer=issuer, client_id="c", client_secret=SECRET)
    assert SECRET not in str(exc.value)


def test_config_off_by_default_and_complete_when_on() -> None:
    assert SsoConfig().enabled is False
    with pytest.raises(ValidationError):
        SsoConfig(enabled=True, issuer=ISSUER, client_id="c")


def test_blank_values_from_compose_mean_unset() -> None:
    from pathlib import Path

    from app.core.config import load_config

    env = {
        "APP__SSO__ENABLED": "false",
        "APP__SSO__ISSUER": "",
        "APP__SSO__CLIENT_ID": "",
        "APP__SSO__CLIENT_SECRET": "",
        "APP__SSO__REQUIRED_GROUPS": "",
        "APP__SERVER__PUBLIC_URL": "",
    }
    config = load_config(Path("missing.yaml"), env)
    assert config.sso.issuer is None and config.sso.required_groups == []
    assert config.server.public_url is None


def test_full_flow_store_refuses_new_flows_instead_of_dropping(
    idp: FakeIdp, client: OidcClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.auth import oidc

    monkeypatch.setattr(oidc, "MAX_FLOWS", 2)
    first_url, first_cookie = client.begin()
    client.begin()
    with pytest.raises(SsoRefusedError) as exc:
        client.begin()
    assert exc.value.code == "unavailable"
    state, code = idp.approve(first_url, "sub-1")
    identity, _ = client.finish(state, code, first_cookie)  # the first sign-in still completes
    assert identity.subject == "sub-1"


def test_failed_discovery_is_not_retried_at_once(idp: FakeIdp, client: OidcClient) -> None:
    idp.discovery_issuer = "https://evil.example.test/v2.0"
    with pytest.raises(SsoRefusedError):
        client.begin()
    idp.discovery_issuer = ISSUER
    with pytest.raises(SsoRefusedError) as exc:
        client.begin()  # within the retry pause: no new request to the provider
    assert "not retrying" in exc.value.reason


def test_issuer_with_trailing_slash_from_discovery(idp: FakeIdp, clock: Clock) -> None:
    idp.discovery_issuer = ISSUER + "/"
    idp.override = {"iss": ISSUER + "/"}
    config = SsoConfig(enabled=True, issuer=ISSUER + "/", client_id=CLIENT_ID, client_secret=SECRET)
    client = OidcClient(config, REDIRECT, clock, http=idp.client)
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    identity, _ = client.finish(state, code, cookie)
    assert identity.issuer == ISSUER + "/"


def test_odd_claim_names_do_not_crash(idp: FakeIdp, client: OidcClient) -> None:
    idp.override = {"_claim_names": 5}
    url, cookie = client.begin()
    state, code = idp.approve(url, "sub-1")
    identity, _ = client.finish(state, code, cookie)
    assert identity.groups == ()
