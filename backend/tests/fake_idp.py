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
            return httpx.Response(
                200,
                json={
                    "issuer": self.discovery_issuer,
                    "authorization_endpoint": f"https://login.example.test/{TENANT}/authorize",
                    "token_endpoint": f"https://login.example.test/{TENANT}/token",
                    "jwks_uri": f"https://login.example.test/{TENANT}/keys",
                },
            )
        if path.endswith("/keys"):
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": self.kid, "use": "sig"}]})
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            entry = self.codes.pop(form.get("code", [""])[0], None)
            if (
                entry is None
                or form.get("client_secret") != [SECRET]
                or form.get("client_id") != [CLIENT_ID]
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
            token = jwt.encode(
                claims, self.sign_key or self.key, algorithm="RS256", headers={"kid": self.kid}
            )
            return httpx.Response(200, json={"id_token": token, "token_type": "Bearer"})
        return httpx.Response(404, json={"error": "not_found"})
