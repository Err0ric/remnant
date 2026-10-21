"""Fake Microsoft 365 (Entra token endpoint, Management Activity API, Graph) and Anthropic
Admin API servers behind one httpx MockTransport. Requests arrive at the pinned address,
so the fake routes on the Host header, the way the real services see them."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

TENANT = "11111111-2222-4333-8444-555555555555"
CLIENT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclass
class FakeApis:
    # Management Activity: content type -> [(contentCreated, records)]
    blobs: dict[str, list[tuple[str, list[dict[str, Any]]]]] = field(default_factory=dict)
    # Graph: path -> records (filtered by the time field in the request)
    graph: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Anthropic: path -> list of pages (each a response body)
    anthropic: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    forms: list[dict[str, list[str]]] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    fail: dict[str, httpx.Response] = field(default_factory=dict)  # path prefix -> reply
    secret: str = "m365-client-s3cret"
    api_key: str = "sk-ant-admin01-s3cret"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        host = req.headers["host"]
        path = req.url.path
        for prefix, reply in self.fail.items():
            if path.startswith(prefix):
                return reply
        if host == "login.microsoftonline.com":
            return self._token(req)
        if host == "manage.office.com":
            return self._manage(req)
        if host == "graph.microsoft.com":
            return self._graph(req)
        if host == "api.anthropic.com":
            return self._anthropic(req)
        return httpx.Response(404)

    # --- Microsoft -------------------------------------------------------------------

    def _token(self, req: httpx.Request) -> httpx.Response:
        form = parse_qs(req.content.decode())
        self.forms.append(form)
        if req.url.path != f"/{TENANT}/oauth2/v2.0/token":
            return httpx.Response(400, json={"error": "invalid_request", "error_codes": [90002]})
        if form.get("client_secret") != [self.secret] and "client_assertion" not in form:
            return httpx.Response(401, json={"error": "invalid_client", "error_codes": [7000215]})
        scope = form["scope"][0]
        return httpx.Response(200, json={"access_token": f"tok:{scope}", "expires_in": 3599})

    def _authorized(self, req: httpx.Request, host: str) -> bool:
        return req.headers.get("authorization") == f"Bearer tok:https://{host}/.default"

    def _manage(self, req: httpx.Request) -> httpx.Response:
        if not self._authorized(req, "manage.office.com"):
            return httpx.Response(401)
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(req.url)).query).items()}
        root = f"/api/v1.0/{TENANT}/activity/feed"
        if req.url.path == f"{root}/subscriptions/start":
            self.started.append(q["contentType"])
            return httpx.Response(200, json={"status": "enabled"})
        if req.url.path == f"{root}/subscriptions/content":
            start, end = _t(q["startTime"]), _t(q["endTime"])
            ct = q["contentType"]
            listed = [
                {
                    "contentType": ct,
                    "contentId": f"{ct}-{i}",
                    "contentUri": f"https://manage.office.com{root}/audit/{ct}-{i}",
                    "contentCreated": created,
                }
                for i, (created, _) in enumerate(self.blobs.get(ct, []))
                if start <= _t(created) < end
            ]
            return httpx.Response(200, json=listed)
        if req.url.path.startswith(f"{root}/audit/"):
            blob_id = req.url.path.rsplit("/", 1)[1]
            ct, idx = blob_id.rsplit("-", 1)
            return httpx.Response(200, json=self.blobs[ct][int(idx)][1])
        return httpx.Response(404)

    def _graph(self, req: httpx.Request) -> httpx.Response:
        if not self._authorized(req, "graph.microsoft.com"):
            return httpx.Response(401)
        path = req.url.path.removeprefix("/v1.0/")
        flt = parse_qs(urlsplit(str(req.url)).query)["$filter"][0]
        fld, _, lo, _, _, _, hi = flt.split(" ")
        rows = [r for r in self.graph.get(path, []) if _t(lo) <= _t(str(r[fld])) < _t(hi)]
        return httpx.Response(200, json={"value": rows})

    # --- Anthropic -------------------------------------------------------------------

    def _anthropic(self, req: httpx.Request) -> httpx.Response:
        if req.headers.get("x-api-key") != self.api_key:
            return httpx.Response(401, json={"type": "error"})
        if req.headers.get("anthropic-version") != "2023-06-01":
            return httpx.Response(400)
        pages = self.anthropic.get(req.url.path)
        if pages is None:
            return httpx.Response(404)
        q = parse_qs(urlsplit(str(req.url)).query)
        token = (q.get("page") or q.get("after_id") or ["0"])[0]
        index = int(token.removeprefix("p")) if token.removeprefix("p").isdigit() else 0
        body = dict(pages[index]) if index < len(pages) else {"data": [], "has_more": False}
        more = index + 1 < len(pages)
        if "created_at.gte" in q:  # the audit feed filters by time; reports do not here
            since = _t(q["created_at.gte"][0])
            body["data"] = [x for x in body.get("data", []) if _t(x["created_at"]) >= since]
        body["has_more"] = more
        body["next_page"] = f"p{index + 1}" if more else None
        body["last_id"] = f"p{index + 1}" if more else None
        return httpx.Response(200, content=json.dumps(body).encode())
