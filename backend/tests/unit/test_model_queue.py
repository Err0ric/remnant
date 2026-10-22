"""One queue per model provider; busy is not down (ADR-0028, D78)."""

import threading
import time
from typing import Any

import pytest

from app.core.errors import (
    CallCancelledError,
    ClassificationBlockedError,
    ProviderBusyError,
    ProviderConfigError,
)
from app.llm import gate as gate_module
from app.llm.provider import ProviderResponse
from app.llm.queue import CANCELLED, QUEUES, slots_for
from tests.unit.test_llm_gate import CLOUD_URL, LOCAL_URL, Lab, calls, lab, provider, request

__all__ = ["lab"]  # the fixture, imported for these tests

OK = ProviderResponse(text='{"sql": "SELECT 1"}', model="m")


class Scripted:
    """Answers in order (an exception is raised); tracks how many calls run at once."""

    def __init__(self, script: list[Any], hold_s: float = 0.0) -> None:
        self.script = script
        self.hold_s = hold_s
        self.lock = threading.Lock()
        self.now = 0
        self.most = 0
        self.calls = 0

    def chat(self, *a: Any, **k: Any) -> ProviderResponse:
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
            step = self.script[min(self.calls, len(self.script) - 1)]
            self.calls += 1
        try:
            time.sleep(self.hold_s)
            if isinstance(step, Exception):
                raise step
            return step  # type: ignore[no-any-return]  # scripted answer
        finally:
            with self.lock:
                self.now -= 1

    def models(self) -> list[str]:
        return ["m"]


def use(lab: Lab, fake: Scripted) -> None:
    lab.gate._factory = lambda *a: fake  # type: ignore[assignment]  # test double


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate_module, "backoff_s", lambda attempt, after: 0.05)


def test_two_requests_with_one_slot_run_one_after_the_other(lab: Lab) -> None:
    pid = provider(lab, LOCAL_URL)
    fake = Scripted([OK], hold_s=0.3)
    use(lab, fake)
    out: list[Any] = []
    threads = [
        threading.Thread(target=lambda: out.append(lab.gate.call(request(lab, pid, ["fw_edge"]))))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 2 and fake.most == 1
    waits = sorted(r["queue_wait_ms"] for r in calls(lab))
    assert waits[0] < 100 <= waits[1]  # the second waited for the first


def test_busy_answers_are_retried_and_counted(lab: Lab) -> None:
    pid = provider(lab, LOCAL_URL)
    fake = Scripted([ProviderBusyError("busy"), ProviderBusyError("busy", 1), OK])
    use(lab, fake)
    lab.gate.call(request(lab, pid, ["fw_edge"]))
    (row,) = calls(lab)
    assert (row["busy_retries"], row["error"]) == (2, None)


def test_busy_past_the_budget_is_provider_busy(lab: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate_module, "DEFAULT_WAIT_S", 1)
    pid = provider(lab, LOCAL_URL)
    use(lab, Scripted([ProviderBusyError("busy")]))
    with pytest.raises(ProviderBusyError, match="busy"):
        lab.gate.call(request(lab, pid, ["fw_edge"]))
    (row,) = calls(lab)
    assert row["error"] == "provider_busy" and row["busy_retries"] >= 1


def test_cancel_while_waiting_leaves_the_queue_and_is_audited(lab: Lab) -> None:
    pid = provider(lab, LOCAL_URL)
    use(lab, Scripted([OK]))
    QUEUES.acquire(pid, 1, time.monotonic() + 5)  # another call holds the only slot
    token = CANCELLED.set(lambda: True)
    try:
        with pytest.raises(CallCancelledError):
            lab.gate.call(request(lab, pid, ["fw_edge"]))
    finally:
        CANCELLED.reset(token)
        QUEUES.release(pid)
    assert calls(lab)[0]["error"] == "cancelled"
    assert QUEUES.status(pid).waiting == 0


def test_health_check_takes_no_slot_and_busy_is_not_down(lab: Lab) -> None:
    pid = provider(lab, "http://127.0.0.1:9/v1")  # nothing listens: refused
    record = lab.store.get(pid)
    down = gate_module.health(record, lab.store, [])
    assert not down.ok and not down.busy
    QUEUES.acquire(pid, 1, time.monotonic() + 5)  # a long inference holds the slot
    try:
        busy = gate_module.health(record, lab.store, [])
    finally:
        QUEUES.release(pid)
    assert busy.ok and busy.busy and busy.detail.startswith("Busy")


def test_cloud_providers_have_no_queue_unless_set(lab: Lab) -> None:
    assert slots_for(None, local=False) is None
    assert slots_for(None, local=True) == 1
    assert slots_for(3, local=False) == 3
    pid = provider(lab, CLOUD_URL)
    fake = Scripted([OK], hold_s=0.3)
    use(lab, fake)
    threads = [
        threading.Thread(target=lambda: lab.gate.call(request(lab, pid, ["fw_edge"])))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert fake.most == 2


class Then(Scripted):
    """Scripted, running `between` after the first attempt (an admin acting mid-wait)."""

    def __init__(self, script: list[Any], between: Any) -> None:
        super().__init__(script)
        self.between = between

    def chat(self, *a: Any, **k: Any) -> ProviderResponse:
        try:
            return super().chat(*a, **k)
        finally:
            if self.calls == 1:
                self.between()


def test_source_flipped_to_local_only_before_a_retry_is_blocked(lab: Lab) -> None:
    pid = provider(lab, CLOUD_URL)
    lab.store.update(pid, None, None, None, None, None, False, max_concurrent=1)  # retries on

    def flip() -> None:
        with lab.meta.connect() as con:
            con.execute(
                "UPDATE sources SET classification = 'local_only' WHERE source_id = 'fw_edge'"
            )

    fake = Then([ProviderBusyError("busy"), OK], flip)
    use(lab, fake)
    with pytest.raises(ClassificationBlockedError, match="now includes local-only"):
        lab.gate.call(request(lab, pid, ["fw_edge"]))
    assert fake.calls == 1  # nothing sent after the flip
    (row,) = calls(lab)
    assert (row["error"], row["busy_retries"]) == ("classification_blocked", 1)


def test_provider_disabled_during_the_wait_is_refused(lab: Lab) -> None:
    pid = provider(lab, LOCAL_URL)
    fake = Then(
        [ProviderBusyError("busy"), OK],
        lambda: lab.store.update(pid, None, None, None, False, None, False),
    )
    use(lab, fake)
    with pytest.raises(ProviderConfigError, match="disabled"):
        lab.gate.call(request(lab, pid, ["fw_edge"]))
    assert fake.calls == 1
    (row,) = calls(lab)
    assert (row["error"], row["busy_retries"]) == ("provider_disabled", 1)


def test_provider_address_changed_during_the_wait_is_refused(lab: Lab) -> None:
    pid = provider(lab, LOCAL_URL)
    fake = Then(
        [ProviderBusyError("busy"), OK],
        lambda: lab.store.update(pid, None, "http://127.0.0.2:11434/v1", None, None, None, False),
    )
    use(lab, fake)
    with pytest.raises(ProviderConfigError, match="address changed"):
        lab.gate.call(request(lab, pid, ["fw_edge"]))
    assert fake.calls == 1 and calls(lab)[0]["error"] == "provider_changed"


def test_cloud_busy_is_not_retried_without_max_concurrent(lab: Lab) -> None:
    pid = provider(lab, CLOUD_URL)
    fake = Scripted([ProviderBusyError("busy", 7), OK])
    use(lab, fake)
    with pytest.raises(ProviderBusyError) as caught:
        lab.gate.call(request(lab, pid, ["fw_edge"]))
    assert caught.value.retry_after_s == 7  # the provider's Retry-After, passed on
    assert fake.calls == 1
    (row,) = calls(lab)
    assert (row["error"], row["busy_retries"]) == ("provider_busy", 0)
