"""OpenID Connect authorization code flow with PKCE (ADR-0013).

This module knows the protocol only: discovery, the authorize URL, the code exchange, and
ID token checks. Which account a verified identity maps to is decided in `auth.service`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus, urlencode

import httpx
import jwt

from app.core.config import SsoConfig
from app.core.errors import SsoRefusedError

FLOW_TTL = timedelta(minutes=10)
MAX_FLOWS = 1000  # open sign-ins at once; new ones are refused beyond this, none dropped
DISCOVERY_TTL_S = 3600
DISCOVERY_RETRY_S = 30  # after a failed discovery, fail fast for this long
KEY_REFRESH_MIN_S = 60
LEEWAY_S = 120
ALGORITHMS = ["RS256", "ES256"]
SCOPES = ("openid", "profile")
AuthMethod = str  # "client_secret_basic" or "client_secret_post"
MAX_RESPONSE_BYTES = 256 * 1024

HttpFactory = Callable[[], httpx.Client]


def _default_http() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _challenge(verifier: str) -> str:
    raw = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class Endpoints:
    issuer: str  # exactly as the provider writes it (some end in a slash)
    authorization: str
    token: str
    jwks: str
    userinfo: str | None = None
    auth_methods: tuple[str, ...] = ()  # token_endpoint_auth_methods_supported


@dataclass(frozen=True, slots=True)
class Identity:
    issuer: str
    subject: str
    name: str  # display only (preferred_username or name); never used to find an account
    groups: tuple[str, ...] | None  # None when the token says the list was too long


@dataclass(frozen=True, slots=True)
class _Flow:
    nonce: str
    verifier: str
    binding: str  # SHA-256 of the browser cookie value
    link_token: str | None  # invite or reset link this sign-in finishes, if any
    expires_at: datetime


class OidcClient:
    def __init__(
        self,
        config: SsoConfig,
        redirect_uri: str,
        clock: Callable[[], datetime],
        http: HttpFactory = _default_http,
    ) -> None:
        if not (config.enabled and config.issuer and config.client_id and config.client_secret):
            raise ValueError("OidcClient needs an enabled, complete SSO config")
        self.issuer = config.issuer.rstrip("/")
        self._client_id = config.client_id
        self._secret = config.client_secret
        self._scopes = " ".join(dict.fromkeys((*SCOPES, *config.extra_scopes)))
        self._auth_method = config.token_auth_method
        # Groups are needed only to check REQUIRED_GROUPS; then a provider that keeps them
        # out of the ID token (Authelia, by default) is asked through UserInfo.
        self._want_groups = bool(config.required_groups)
        self.redirect_uri = redirect_uri
        self._clock = clock
        self._http = http
        self._lock = threading.Lock()
        self._flows: dict[str, _Flow] = {}
        self._endpoints: tuple[float, Endpoints] | None = None
        self._discovery_failed_at = float("-inf")
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_at = 0.0

    # --- start ---------------------------------------------------------------------------

    def begin(self, link_token: str | None = None) -> tuple[str, str]:
        """Returns (provider URL to send the browser to, value for the flow cookie)."""
        endpoints = self._discover()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        cookie = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            self._drop_expired(now)
            if len(self._flows) >= MAX_FLOWS:
                # Refuse rather than drop: dropping would let a flood cancel real sign-ins.
                raise SsoRefusedError("unavailable", "too many sign-ins in progress")
            self._flows[_digest(state)] = _Flow(
                nonce, verifier, _digest(cookie), link_token, now + FLOW_TTL
            )
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": self._scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
                "response_mode": "query",
            }
        )
        return f"{endpoints.authorization}?{query}", cookie

    # --- callback ------------------------------------------------------------------------

    def finish(self, state: str, code: str, cookie: str | None) -> tuple[Identity, str | None]:
        """Check the flow, exchange the code, verify the ID token.

        Returns the identity and the link token the flow was started with, if any.
        """
        flow = self.take_flow(state, cookie)
        id_token, access_token = self._exchange(code, flow.verifier)
        identity, claims = self._verify(id_token, flow.nonce)
        missing_groups = self._want_groups and "groups" not in claims and identity.groups == ()
        if (missing_groups or not identity.name) and access_token:
            identity = self._with_userinfo(identity, access_token, missing_groups)
        return identity, flow.link_token

    def take_flow(self, state: str, cookie: str | None) -> _Flow:
        """Remove and return the flow for `state` if it belongs to this browser and is live."""
        now = self._clock()
        with self._lock:
            flow = self._flows.pop(_digest(state), None)
            self._drop_expired(now)
        if flow is None or flow.expires_at <= now:
            raise SsoRefusedError("expired", "flow not found or expired")
        if cookie is None or not hmac.compare_digest(flow.binding, _digest(cookie)):
            raise SsoRefusedError("invalid", "flow cookie missing or does not match")
        return flow

    def _method(self, endpoints: Endpoints) -> AuthMethod:
        """How to send the client secret: as configured, or what the provider prefers."""
        if self._auth_method != "auto":
            return self._auth_method
        offered = endpoints.auth_methods
        if not offered or "client_secret_basic" in offered:
            return "client_secret_basic"  # the OIDC default when a provider does not say
        return "client_secret_post"

    def _exchange(self, code: str, verifier: str) -> tuple[str, str | None]:
        """The ID token and, if given, the access token (for UserInfo only)."""
        endpoints = self._discover()
        assert self._secret is not None
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        }
        headers = {"Accept": "application/json"}
        if self._method(endpoints) == "client_secret_basic":
            # RFC 6749 2.3.1: both parts form-urlencoded before the Basic encoding.
            pair = f"{quote_plus(self._client_id)}:{quote_plus(self._secret.get_secret_value())}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            form |= {"client_id": self._client_id, "client_secret": self._secret.get_secret_value()}
        try:
            with self._http() as client:
                res = client.post(
                    endpoints.token,
                    data=form,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise SsoRefusedError("unavailable", f"token endpoint: {type(exc).__name__}") from exc
        payload = self._json(res, "token endpoint")
        token = payload.get("id_token")
        if res.status_code != 200 or not isinstance(token, str):
            error = str(payload.get("error", res.status_code))[:100]
            raise SsoRefusedError("invalid", f"token endpoint refused the code: {error}")
        access = payload.get("access_token")
        return token, access if isinstance(access, str) else None

    def _with_userinfo(self, identity: Identity, access_token: str, groups: bool) -> Identity:
        """Fill groups or the display name from UserInfo. Its `sub` must match the ID
        token's (OIDC Core 5.3.2), or the answer is about someone else and is refused."""
        endpoints = self._discover()
        if endpoints.userinfo is None:
            return identity
        try:
            with self._http() as client:
                res = client.get(
                    endpoints.userinfo,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise SsoRefusedError("unavailable", f"userinfo: {type(exc).__name__}") from exc
        if res.status_code != 200:
            raise SsoRefusedError("unavailable", f"userinfo answered {res.status_code}")
        info = self._json(res, "userinfo")
        if info.get("sub") != identity.subject:
            raise SsoRefusedError("invalid", "userinfo is for another subject")
        found = identity.groups
        if groups and isinstance(info.get("groups"), list):
            found = tuple(str(g) for g in info["groups"])
        name = identity.name or str(info.get("preferred_username") or info.get("name") or "")
        return Identity(identity.issuer, identity.subject, name[:200], found)

    def _verify(self, id_token: str, nonce: str) -> tuple[Identity, dict[str, Any]]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise SsoRefusedError("invalid", "ID token is not a JWT") from exc
        if header.get("alg") not in ALGORITHMS or not isinstance(header.get("kid"), str):
            raise SsoRefusedError("invalid", f"ID token algorithm {header.get('alg')!r} refused")
        key = self._key(header["kid"])
        issuer = self._discover().issuer
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=ALGORITHMS,
                audience=self._client_id,
                issuer=issuer,
                leeway=LEEWAY_S,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
            )
        except jwt.PyJWTError as exc:
            raise SsoRefusedError(
                "invalid", f"ID token check failed: {type(exc).__name__}"
            ) from exc
        if not hmac.compare_digest(str(claims["nonce"]), nonce):
            raise SsoRefusedError("invalid", "ID token nonce does not match")
        if "azp" in claims and claims["azp"] != self._client_id:
            raise SsoRefusedError("invalid", "ID token azp is another client")
        groups: tuple[str, ...] | None
        raw_groups = claims.get("groups")
        if isinstance(raw_groups, list):
            groups = tuple(str(g) for g in raw_groups)
        elif (
            isinstance(claims.get("_claim_names"), dict) and "groups" in claims["_claim_names"]
        ) or claims.get("hasgroups"):
            groups = None  # Entra group overage: the list was too long to include
        else:
            groups = ()
        name = str(claims.get("preferred_username") or claims.get("name") or "")[:200]
        return Identity(str(claims["iss"]), str(claims["sub"]), name, groups), claims

    # --- provider metadata ---------------------------------------------------------------

    def _discover(self) -> Endpoints:
        cached = self._endpoints
        if cached and time.monotonic() - cached[0] < DISCOVERY_TTL_S:
            return cached[1]
        if time.monotonic() - self._discovery_failed_at < DISCOVERY_RETRY_S:
            raise SsoRefusedError("unavailable", "discovery failed moments ago; not retrying yet")
        try:
            endpoints = self._fetch_discovery()
        except SsoRefusedError:
            self._discovery_failed_at = time.monotonic()
            raise
        self._endpoints = (time.monotonic(), endpoints)
        return endpoints

    def _fetch_discovery(self) -> Endpoints:
        url = f"{self.issuer}/.well-known/openid-configuration"
        try:
            with self._http() as client:
                res = client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise SsoRefusedError("unavailable", f"discovery: {type(exc).__name__}") from exc
        doc = self._json(res, "discovery")
        issuer = doc.get("issuer")
        if (
            res.status_code != 200
            or not isinstance(issuer, str)
            or issuer.rstrip("/") != self.issuer
        ):
            raise SsoRefusedError("unavailable", "discovery document is for another issuer")
        fields = ("authorization_endpoint", "token_endpoint", "jwks_uri")
        values = [doc.get(f) for f in fields]
        if not all(isinstance(v, str) and v.startswith("https://") for v in values):
            raise SsoRefusedError("unavailable", "discovery endpoints must be https")
        userinfo = doc.get("userinfo_endpoint")
        if not (isinstance(userinfo, str) and userinfo.startswith("https://")):
            userinfo = None
        methods = doc.get("token_endpoint_auth_methods_supported")
        offered = (
            tuple(m for m in methods if isinstance(m, str)) if isinstance(methods, list) else ()
        )
        auth_url, token_url, jwks_url = (str(v) for v in values)
        return Endpoints(issuer, auth_url, token_url, jwks_url, userinfo, offered)

    def _key(self, kid: str) -> jwt.PyJWK:
        key = self._keys.get(kid)
        if key is not None:
            return key
        if time.monotonic() - self._keys_at < KEY_REFRESH_MIN_S and self._keys:
            raise SsoRefusedError("invalid", "ID token signed with an unknown key")
        endpoints = self._discover()
        try:
            with self._http() as client:
                res = client.get(endpoints.jwks, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise SsoRefusedError("unavailable", f"keys: {type(exc).__name__}") from exc
        doc = self._json(res, "keys")
        keys: dict[str, jwt.PyJWK] = {}
        for item in doc.get("keys", []) if isinstance(doc.get("keys"), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("kid"), str):
                continue
            try:
                keys[item["kid"]] = jwt.PyJWK(item)
            except jwt.PyJWTError:
                continue  # a key type we do not use (for example an encryption key)
        self._keys, self._keys_at = keys, time.monotonic()
        if kid not in keys:
            raise SsoRefusedError("invalid", "ID token signed with an unknown key")
        return keys[kid]

    @staticmethod
    def _json(res: httpx.Response, what: str) -> dict[str, Any]:
        if len(res.content) > MAX_RESPONSE_BYTES:
            raise SsoRefusedError("unavailable", f"{what} response too large")
        try:
            data = res.json()
        except ValueError as exc:
            raise SsoRefusedError("unavailable", f"{what} did not return JSON") from exc
        if not isinstance(data, dict):
            raise SsoRefusedError("unavailable", f"{what} did not return an object")
        return data

    def _drop_expired(self, now: datetime) -> None:
        for key in [k for k, f in self._flows.items() if f.expires_at <= now]:
            del self._flows[key]
