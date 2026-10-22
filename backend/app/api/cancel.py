"""Cancel a waiting model call when the browser goes away (ADR-0028 row 6)."""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.requests import Request

from app.llm.queue import CANCELLED, POLL_S


@asynccontextmanager
async def watch_disconnect(request: Request) -> AsyncIterator[None]:
    """For the duration of a handler: mark the gate's wait cancelled if the client leaves."""
    gone = threading.Event()

    async def watch() -> None:
        while not gone.is_set():
            if await request.is_disconnected():
                gone.set()
                return
            await asyncio.sleep(POLL_S)

    task = asyncio.create_task(watch())
    token = CANCELLED.set(gone.is_set)
    try:
        yield
    finally:
        CANCELLED.reset(token)
        task.cancel()
