"""An in-process OpenID Connect provider shaped like Microsoft Entra ID, for tests.

Serves discovery, keys, and a token endpoint through httpx.MockTransport. Tests choose the
claims the next ID token carries, or tamper with it, through attributes on the instance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

TENANT = "11111111-2222-3333-4444-555555555555"
ISSUER = f"https://login.example.test/{TENANT}/v2.0"
CLIENT_ID = "app-client-id"
SECRET = "test-client-secret"  # a test value


def _challenge(verifier: str) -> str:
    raw = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class FakeIdp:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.codes: dict[str, dict[str, Any]] = {}  # code -> {nonce, verifier, claims}
        self.token_requests: list[dict[str, list[str]]] = []
        self.discovery_issuer = ISSUER
        self.override: dict[str, Any] = {}  # extra or replaced claims for the next token
        self.sign_key: Any = None  # sign with another key to test rejection
        # Authelia-like behaviour: which secret methods discovery offers (None: not listed),
        # and claims that only UserInfo returns.
        self.auth_methods: list[str] | None = None
        self.userinfo_only: set[str] = set()
        self.userinfo_sub: str | None = None  # answer UserInfo for another subject
        self.userinfo_calls = 0
        self.tokens: dict[str, dict[str, Any]] = {}  # access token -> claims

    # What the browser would do at the provider: approve and come back with a code.
    def approve(self, authorize_url: str, sub: str, **claims: Any) -> tuple[str, str]:
        query = parse_qs(httpx.URL(authorize_url).query.decode())
        code = f"code-{len(self.codes)}"
        self.codes[code] = {
            "nonce": query["nonce"][0],
            "challenge": query["code_challenge"][0],
            "claims": {"sub": sub, **claims},
        }
        return query["state"][0], code

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport())

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            doc = {
                "issuer": self.discovery_issuer,
                "authorization_endpoint": f"https://login.example.test/{TENANT}/authorize",
                "token_endpoint": f"https://login.example.test/{TENANT}/token",
                "jwks_uri": f"https://login.example.test/{TENANT}/keys",
                "userinfo_endpoint": f"https://login.example.test/{TENANT}/userinfo",
            }
            if self.auth_methods is not None:
                doc["token_endpoint_auth_methods_supported"] = self.auth_methods
            return httpx.Response(200, json=doc)
        if path.endswith("/userinfo"):
            self.userinfo_calls += 1
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            info = self.tokens.get(bearer)
            if info is None:
                return httpx.Response(401, json={"error": "invalid_token"})
            return httpx.Response(200, json={**info, "sub": self.userinfo_sub or info["sub"]})
        if path.endswith("/keys"):
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": self.kid, "use": "sig"}]})
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            self.token_requests.append(
                {**form, "_auth": [request.headers.get("authorization", "")]}
            )
            entry = self.codes.pop(form.get("code", [""])[0], None)
            basic = "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
            by_basic = request.headers.get("authorization") == basic
            by_post = form.get("client_secret") == [SECRET] and form.get("client_id") == [CLIENT_ID]
            allowed = self.auth_methods or ["client_secret_basic", "client_secret_post"]
            authed = (by_basic and "client_secret_basic" in allowed) or (
                by_post and "client_secret_post" in allowed
            )
            if (
                entry is None
                or not authed
                or _challenge(form.get("code_verifier", [""])[0]) != entry["challenge"]
            ):
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "iat": now,
                "nbf": now,
                "exp": now + 3600,
                "nonce": entry["nonce"],
                "tid": TENANT,
                **entry["claims"],
                **self.override,
            }
            in_token = {k: v for k, v in claims.items() if k not in self.userinfo_only}
            token = jwt.encode(
                in_token, self.sign_key or self.key, algorithm="RS256", headers={"kid": self.kid}
            )
            access = f"at-{len(self.tokens)}"
            self.tokens[access] = {k: v for k, v in claims.items() if k in self.userinfo_only} | {
                "sub": claims["sub"]
            }
            return httpx.Response(
                200, json={"id_token": token, "access_token": access, "token_type": "Bearer"}
            )
        return httpx.Response(404, json={"error": "not_found"})
