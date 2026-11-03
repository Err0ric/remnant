"""Owner, 2026-11-03: Settings > AI providers shows whether a local Ollama model is on GPU
or CPU, and its context length, from Ollama's /api/ps. Read-only; local providers only."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.llm import gate
from app.llm.providers.openai_compat import OpenAICompatibleProvider
from tests.integration.test_llm_providers import _dns, admin  # noqa: F401  # fixture

PS = {
    "models": [
        {
            "name": "gemma4:26b",
            "model": "gemma4:26b",
            "size": 18_000_000_000,
            "size_vram": 0,
            "context_length": 65536,
            "expires_at": "2026-11-03T21:00:00Z",
        },
        {"name": "qwen3.5:9b", "size": 7_000_000_000, "size_vram": 3_500_000_000},
        {"name": "qwen3.5:4b", "size": 4_000_000_000, "size_vram": 4_000_000_000},
    ]
}


def _served(monkeypatch: pytest.MonkeyPatch, status: int, body: Any) -> list[str]:
    seen: list[str] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.path}")
        return httpx.Response(status, content=json.dumps(body).encode())

    real = gate.build_provider

    def build(record: Any, store: Any, endpoint: Any) -> Any:
        p = real(record, store, endpoint)
        if isinstance(p, OpenAICompatibleProvider):
            t = httpx.MockTransport(handle)
            p._http._transport = t  # the test's server
            p._native._transport = t
        return p

    monkeypatch.setattr(gate, "build_provider", build)
    return seen


def test_a_local_ollama_model_shows_cpu_or_gpu_and_its_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, h = admin(tmp_path)
    pid = c.get("/api/providers").json()[0]["provider_id"]  # Local Ollama, http://ollama:11434/v1
    c.patch(f"/api/providers/{pid}", json={"model": "gemma4:26b"}, headers=h)
    seen = _served(monkeypatch, 200, PS)
    out = c.get(f"/api/providers/{pid}/runtime").json()
    assert seen == ["GET /api/ps"]  # Ollama's own API beside /v1; nothing sent
    assert out["available"] is True
    by = {m["name"]: m for m in out["models"]}
    assert by["gemma4:26b"] == {
        "name": "gemma4:26b", "placement": "cpu", "gpu_percent": 0,
        "size_bytes": 18_000_000_000, "context": 65536,
        "until": "2026-11-03T21:00:00Z", "configured": True,
    }  # fmt: skip
    assert by["qwen3.5:9b"]["placement"] == "split" and by["qwen3.5:9b"]["gpu_percent"] == 50
    assert by["qwen3.5:9b"]["context"] is None  # older Ollama does not report it
    assert by["qwen3.5:4b"]["placement"] == "gpu" and not by["qwen3.5:4b"]["configured"]


def test_not_ollama_and_cloud_providers_report_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, h = admin(tmp_path)
    pid = c.get("/api/providers").json()[0]["provider_id"]
    _served(monkeypatch, 404, {"error": "not found"})  # LM Studio, vLLM, llama.cpp
    assert c.get(f"/api/providers/{pid}/runtime").json() == {"available": False, "models": []}
    seen = _served(monkeypatch, 200, PS)
    cloud = c.post(
        "/api/providers",
        json={"name": "Cloud", "base_url": "https://api.cloud.example/v1", "model": "m",
              "acknowledge_cloud": True},
        headers=h,
    ).json()  # fmt: skip
    assert c.get(f"/api/providers/{cloud['provider_id']}/runtime").json()["available"] is False
    assert seen == []  # a cloud provider is never asked
