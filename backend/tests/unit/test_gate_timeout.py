"""Each Ask model call has a time limit (D270, `ask.model_timeout_s`).

The gate sets a deadline for the provider request; the adapters' HTTP client stops at it
and closes the connection (tested against a real socket below). A timed-out call is
audited with error `timeout` and raises ModelTimeoutError. Waiting for a slot in the
provider's queue is not model time and keeps its own budget (ADR-0028).
"""

import json
import socket
import threading
import time
from dataclasses import dataclass, field

import pytest

from app.core.errors import ModelTimeoutError, ProviderError
from app.llm import provider_http
from app.llm.provider import ChatMessage, ProviderResponse
from app.llm.provider_http import CALL_DEADLINE, deadline_left
from app.llm.providers.openai_compat import OpenAICompatibleProvider
from tests.unit.test_llm_gate import (  # noqa: F401  # fixture
    LOCAL_URL,
    Lab,
    calls,
    lab,
    provider,
    request,
)


@dataclass
class SlowModel:
    """Takes `seconds` to answer, like a CPU-only model server, but stops at the deadline
    the way the HTTP client does (the real client is tested at the end of this file)."""

    seconds: float
    provider_id: str = "p"
    locality: str = "local"
    deadlines: list[float | None] = field(default_factory=list)

    def chat(self, messages, tools=None, json_mode=False, max_tokens=1024, temperature=0.0):  # type: ignore[no-untyped-def]  # test double
        left = deadline_left()
        self.deadlines.append(left)
        if left is not None and left < self.seconds:
            time.sleep(max(left, 0))
            raise ModelTimeoutError("The model took too long to answer.")
        time.sleep(self.seconds)
        return ProviderResponse(text='{"sql": "SELECT 1"}', model="m")

    def models(self) -> list[str]:
        return ["m"]


def _slow(lab: Lab, seconds: float) -> SlowModel:  # noqa: F811
    model = SlowModel(seconds)
    lab.gate._factory = lambda *_: model  # type: ignore[assignment]  # fake satisfies the protocol
    return model


def test_a_slow_ask_call_stops_at_the_limit_and_is_audited(lab: Lab) -> None:  # noqa: F811
    lab.gate.model_timeout_s = 0.3
    model = _slow(lab, 200)
    pid = provider(lab, LOCAL_URL)
    t0 = time.monotonic()
    with pytest.raises(ModelTimeoutError) as got:
        lab.gate.call(request(lab, pid, []))
    assert time.monotonic() - t0 < 2
    assert model.deadlines[0] is not None and 0 < model.deadlines[0] <= 0.3
    (row,) = calls(lab)
    assert row["error"] == "timeout" and row["finished_at"] is not None
    assert row["call_id"] == got.value.call_id  # type: ignore[attr-defined]  # set by the gate
    assert row["latency_ms"] >= 250
    assert CALL_DEADLINE.get() is None  # nothing left set for the next call on this thread


def test_a_call_inside_the_limit_is_unchanged(lab: Lab) -> None:  # noqa: F811
    lab.gate.model_timeout_s = 5
    _slow(lab, 0.01)
    pid = provider(lab, LOCAL_URL)
    assert lab.gate.call(request(lab, pid, [])).response.text == '{"sql": "SELECT 1"}'
    (row,) = calls(lab)
    assert row["error"] is None


def test_the_limit_is_for_ask_calls_only(lab: Lab) -> None:  # noqa: F811
    lab.gate.model_timeout_s = 0.3
    model = _slow(lab, 0.01)
    pid = provider(lab, LOCAL_URL)
    lab.gate.call(request(lab, pid, [], purpose="parser_draft"))
    assert model.deadlines == [None]


def test_the_limit_an_admin_saved_takes_the_place_of_the_config(lab: Lab) -> None:  # noqa: F811
    lab.gate.model_timeout_s = 0.3  # the config's value
    assert lab.gate.time_limit() == (0.3, False)
    lab.gate.set_time_limit(240, "u-admin")
    assert lab.gate.time_limit() == (240, True)
    model = _slow(lab, 0.5)
    pid = provider(lab, LOCAL_URL)
    assert lab.gate.call(request(lab, pid, [])).response.text == '{"sql": "SELECT 1"}'
    assert model.deadlines[0] is not None and 200 < model.deadlines[0] <= 240
    lab.gate.model_timeout_s = 120  # the config changes: the saved value still applies
    assert lab.gate.time_limit() == (240, True)
    lab.gate.set_time_limit(None, "u-admin")  # back to following the config
    assert lab.gate.time_limit() == (120, False)


def test_a_timeout_is_a_provider_error_for_callers_that_catch_those() -> None:
    assert issubclass(ModelTimeoutError, ProviderError)


# --- the HTTP client closes the request at the deadline -----------------------------------


def _silent_server() -> tuple[int, threading.Event, socket.socket]:
    """Accepts one connection, reads the request, never answers; sets `closed` when the
    client hangs up."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    closed = threading.Event()

    def serve() -> None:
        conn, _ = srv.accept()
        conn.settimeout(10)
        try:
            while conn.recv(65536):
                pass
            closed.set()  # recv returned b"": the client closed the connection
        except OSError:
            closed.set()
        finally:
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], closed, srv


def test_the_http_client_closes_the_provider_request_at_the_deadline() -> None:
    port, closed, srv = _silent_server()
    model = OpenAICompatibleProvider(
        provider_id="p1",
        base_url=f"http://127.0.0.1:{port}/v1",
        model="m",
        api_key=None,
        locality="local",
    )
    token = CALL_DEADLINE.set(time.monotonic() + 0.5)
    t0 = time.monotonic()
    try:
        with pytest.raises(ModelTimeoutError):
            model.chat([ChatMessage("user", "hi")])
    finally:
        CALL_DEADLINE.reset(token)
        srv.close()
    assert time.monotonic() - t0 < 2
    assert closed.wait(3), "the provider connection was left open"


def test_no_deadline_keeps_the_client_as_it_was() -> None:
    assert deadline_left() is None


def _late_server(
    headers_after: float, trickle_every: float | None
) -> tuple[int, threading.Event, socket.socket]:
    """Sends the response headers after `headers_after` seconds, then either nothing
    (a stall) or one body byte every `trickle_every` seconds; sets `closed` on hang-up."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    closed = threading.Event()

    def serve() -> None:
        conn, _ = srv.accept()
        try:
            conn.recv(65536)
            time.sleep(headers_after)
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n"
            )
            conn.settimeout(10)
            while True:
                if trickle_every is None:
                    if not conn.recv(65536):
                        break
                else:
                    time.sleep(trickle_every)
                    conn.sendall(b" ")
        except OSError:
            pass
        finally:
            closed.set()
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], closed, srv


@pytest.mark.parametrize("trickle", [None, 0.2], ids=["stall", "trickle"])
def test_one_deadline_covers_headers_and_every_read_after(trickle: float | None) -> None:
    """Headers at 80% of the limit, then a stall or a byte every 0.2 s: the call still
    ends at the limit, not one read timeout later."""
    limit = 1.0
    port, closed, srv = _late_server(0.8 * limit, trickle)
    model = OpenAICompatibleProvider(
        provider_id="p1", base_url=f"http://127.0.0.1:{port}/v1", model="m", api_key=None,
        locality="local",
    )  # fmt: skip
    token = CALL_DEADLINE.set(time.monotonic() + limit)
    t0 = time.monotonic()
    try:
        with pytest.raises(ModelTimeoutError):
            model.chat([ChatMessage("user", "hi")])
    finally:
        CALL_DEADLINE.reset(token)
        srv.close()
    assert time.monotonic() - t0 < limit + 0.3
    assert closed.wait(3), "the provider connection was left open"


# --- a limit above the per-read cap (scaled: 1 unit = 1 ms, the 180 s cap is 0.18 s) ------

COMPLETION = json.dumps(
    {
        "model": "m",
        "choices": [{"message": {"role": "assistant", "content": '{"sql": "SELECT 1"}'}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
).encode()


def _replies_after(seconds: float) -> tuple[int, socket.socket]:
    """A non-streaming model server: the whole reply arrives when it is finished."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        try:
            conn.recv(65536)
            time.sleep(seconds)
            head = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(COMPLETION)}\r\n\r\n"
            conn.sendall(head.encode() + COMPLETION)
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], srv


def _real_model(lab: Lab, port: int) -> None:  # noqa: F811
    lab.gate._factory = lambda record, *_: OpenAICompatibleProvider(  # type: ignore[assignment]  # the real adapter
        provider_id=record.provider_id, base_url=f"http://127.0.0.1:{port}/v1", model="m",
        api_key=None, locality="local",
    )  # fmt: skip


@pytest.fixture
def scaled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(provider_http.CAPS, "read", 0.18)


def test_a_limit_above_the_read_cap_is_honoured(lab: Lab, scaled: None) -> None:  # noqa: F811
    lab.gate.model_timeout_s = 0.3  # "300 s"
    port, srv = _replies_after(0.2)  # "200 s": past the read cap, inside the limit
    _real_model(lab, port)
    try:
        got = lab.gate.call(request(lab, provider(lab, LOCAL_URL), []))
    finally:
        srv.close()
    assert got.response.text == '{"sql": "SELECT 1"}'
    assert calls(lab)[-1]["error"] is None


def test_a_reply_past_a_limit_above_the_read_cap_is_a_timeout(lab: Lab, scaled: None) -> None:  # noqa: F811
    lab.gate.model_timeout_s = 0.3
    port, srv = _replies_after(0.6)
    _real_model(lab, port)
    try:
        with pytest.raises(ModelTimeoutError, match="too long"):
            lab.gate.call(request(lab, provider(lab, LOCAL_URL), []))
    finally:
        srv.close()
    assert calls(lab)[-1]["error"] == "timeout"


def test_without_a_deadline_the_read_cap_still_applies(lab: Lab, scaled: None) -> None:  # noqa: F811
    port, srv = _replies_after(0.6)
    _real_model(lab, port)
    try:
        with pytest.raises(ProviderError, match="ReadTimeout"):  # Explain, drafts, reports
            lab.gate.call(request(lab, provider(lab, LOCAL_URL), [], purpose="parser_draft"))
    finally:
        srv.close()
    assert calls(lab)[-1]["error"] == "provider_error"


def test_a_read_timeout_under_a_deadline_is_never_a_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if a read stops early with time left, the asker gets the time-limit outcome."""
    port, srv = _replies_after(0.6)
    monkeypatch.setattr(provider_http._TimeLeft, "get", lambda self, key, default=None: 0.1)
    model = OpenAICompatibleProvider(
        provider_id="p1", base_url=f"http://127.0.0.1:{port}/v1", model="m", api_key=None,
        locality="local",
    )  # fmt: skip
    token = CALL_DEADLINE.set(time.monotonic() + 5)
    try:
        with pytest.raises(ModelTimeoutError):
            model.chat([ChatMessage("user", "hi")])
    finally:
        CALL_DEADLINE.reset(token)
        srv.close()
