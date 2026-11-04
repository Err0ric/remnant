"""D193 (owner, 2026-11-03): at 00:00 UTC a request that normally takes 4 ms took 13 s.
Every request-pool thread was waiting (page requests queued on query slots while the
closed-day rollups ran), and the sign-in check needed a pool thread too. Sign-in checks now
run on their own threads, and a request that waits over 2 s for a pool thread is logged
with what held the pool."""

import asyncio
import threading
import time
from typing import Any

import httpx
from structlog.testing import capture_logs

from app.core.threads import WORKER_POOL, run_low
from app.main import _rollups
from tests.integration.test_schedules import BASE, make_lab

HOLD_S = 10.0


def test_a_trivial_request_stays_fast_while_the_pool_is_full_at_rollover(
    tmp_path: Any,
) -> None:
    lab = make_lab(tmp_path)
    app = lab["app"]
    release = threading.Event()

    def busy_page() -> dict[str, bool]:
        # A page request parked on a query slot: it holds a request-pool thread.
        release.wait(HOLD_S)
        return {"ok": True}

    app.router.add_api_route("/api/test-busy-page", busy_page, methods=["GET"])
    auth = {"Authorization": lab["ana"].headers["Authorization"]}
    body = {"kind": "panel", "error_id": "e-0a1b2c", "name": "TypeError", "message": "",
            "route": "/dashboard", "build": ""}  # fmt: skip

    async def scenario() -> tuple[float, list[int]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE, headers=auth) as client:
            # The day rollover's closed-day builds, on their low-priority thread.
            rollover = asyncio.get_running_loop().run_in_executor(
                None, lambda: run_low(lambda: _rollups(app))
            )
            pages = [
                asyncio.create_task(client.get("/api/test-busy-page"))
                for _ in range(WORKER_POOL + 10)
            ]
            await asyncio.sleep(0.5)  # every pool thread is taken by now
            started = time.monotonic()
            res = await client.post("/api/client-errors", json=body)
            took = time.monotonic() - started
            assert res.status_code == 204, res.text
            await asyncio.sleep(2.5)  # the queued pages have now waited over 2 s
            release.set()
            codes = [r.status_code for r in await asyncio.gather(*pages)]
            await rollover
            return took, codes

    with capture_logs() as logs:
        took, codes = asyncio.run(scenario())
    assert took < 1.0, f"the sign-in check waited {took:.1f} s for a worker"
    assert codes.count(200) == WORKER_POOL + 10
    # The requests that did wait for a pool thread are named, with how long they waited.
    waits = [x for x in logs if x["event"] == "pool.wait"]
    assert waits, "a request that waited over 2 s for a worker is logged"
    assert waits[0]["job"].endswith("busy_page") and waits[0]["waited_s"] > 2
