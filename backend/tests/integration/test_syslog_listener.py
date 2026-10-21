"""Native syslog listener end to end (ADR-0021): sockets, framing, senders, spool, ingest."""

import asyncio
import socket
import ssl
from pathlib import Path
from typing import Any

import pytest

from app.auth.tls import ensure_self_signed
from app.ingest.listener import FLUSH_EVERY_S, SyslogListeners
from tests.integration.test_schedules import make_lab

LINE = "<34>Oct 11 22:14:15 fw-edge sshd[42]: Failed password for root from 203.0.113.9"
MULTI = "<13>1 2026-10-16T21:00:00Z web-01 app 7 - - first line\n  second line"


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def add(lab: dict[str, Any], sid: str, **syslog: Any) -> Any:
    return lab["admin"].post(
        "/api/sources",
        json={"source_id": sid, "kind": "syslog", "format": "syslog", "syslog": syslog},
        headers=lab["h"],
    )


def rows(lab: dict[str, Any], sid: str) -> list[list[Any]]:
    lab["app"].state.ingest.run_once()
    res = lab["admin"].post(
        "/api/query",
        json={
            "sql": "SELECT raw, device_ip, device_hostname, parse_status FROM events"
            f" WHERE source_id = '{sid}' ORDER BY raw"
        },
        headers=lab["h"],
    )
    assert res.status_code == 200, res.text
    out: list[list[Any]] = res.json()["rows"]
    return out


def listeners(lab: dict[str, Any], tmp_path: Path) -> SyslogListeners:
    tls = ensure_self_signed(tmp_path / "tls", ["127.0.0.1"])
    return SyslogListeners(tmp_path / "data" / "spool", "127.0.0.1", lambda: (tls.cert, tls.key))


async def settle() -> None:
    await asyncio.sleep(FLUSH_EVERY_S * 3)


def test_udp_tcp_and_tls_land_with_raw_intact(lab: dict[str, Any], tmp_path: Path) -> None:
    udp, tcp, tls = free_port(socket.SOCK_DGRAM), free_port(), free_port()
    assert add(lab, "net_udp", protocol="udp", port=udp).status_code == 201
    assert add(lab, "net_tcp", protocol="tcp", port=tcp).status_code == 201
    assert add(lab, "net_tls", protocol="tls", port=tls).status_code == 201
    store = lab["app"].state.sources
    owner = listeners(lab, tmp_path)

    async def scenario() -> None:
        await owner.reconcile(store.list())
        st = owner.status()
        assert all(st[s].listening for s in ("net_udp", "net_tcp", "net_tls")), st
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(LINE.encode() + b"\n", ("127.0.0.1", udp))
        # TCP: octet counting, with a message spanning two lines, split across writes.
        _, w = await asyncio.open_connection("127.0.0.1", tcp)
        framed = f"{len(MULTI.encode())} {MULTI}{len(LINE)} {LINE}".encode()
        w.write(framed[:20])
        await w.drain()
        await asyncio.sleep(0.05)
        w.write(framed[20:])
        await w.drain()
        w.close()
        ctx = ssl.create_default_context(cafile=str(tmp_path / "tls" / "server.crt"))
        _, tw = await asyncio.open_connection("127.0.0.1", tls, ssl=ctx)
        tw.write(LINE.encode() + b"\n")
        await tw.drain()
        tw.close()
        await settle()
        await owner.close()

    asyncio.run(scenario())
    got = rows(lab, "net_udp")
    assert got == [[LINE, "127.0.0.1", "fw-edge", "envelope_only"]]  # no template: envelope only
    tcp_rows = rows(lab, "net_tcp")
    assert [r[0] for r in tcp_rows] == sorted([MULTI, LINE])  # newline kept inside raw
    assert rows(lab, "net_tls")[0][0] == LINE

    listed = {s["source_id"]: s for s in lab["admin"].get("/api/sources", headers=lab["h"]).json()}
    assert listed["net_udp"]["status"]["listener"] is None  # owner closed: not running here


def test_senders_outside_the_allowed_networks_are_dropped_and_counted(
    lab: dict[str, Any], tmp_path: Path
) -> None:
    port = free_port(socket.SOCK_DGRAM)
    assert add(lab, "dmz", port=port, allowed_senders=["10.20.0.0/16"]).status_code == 201
    owner = listeners(lab, tmp_path)

    async def scenario() -> None:
        await owner.reconcile(lab["app"].state.sources.list())
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(3):
                s.sendto(LINE.encode(), ("127.0.0.1", port))
        await settle()
        st = owner.status()["dmz"]
        assert (st.received, st.dropped_not_allowed) == (0, 3)
        assert st.senders["127.0.0.1"].allowed is False
        await owner.close()

    asyncio.run(scenario())
    assert rows(lab, "dmz") == []


def test_port_rules_and_bind_errors(lab: dict[str, Any], tmp_path: Path) -> None:
    port = free_port()
    assert add(lab, "a", protocol="tcp", port=port).status_code == 201
    taken = add(lab, "b", protocol="tls", port=port)
    assert taken.status_code == 400 and "already used by source a" in taken.text
    assert add(lab, "c", protocol="udp", port=port).status_code == 201  # UDP is another space
    assert add(lab, "d", protocol="udp", port=80).status_code == 422  # below 1024
    bad = lab["admin"].post(
        "/api/sources",
        json={"source_id": "e", "kind": "syslog", "format": "json", "syslog": {"port": 6000}},
        headers=lab["h"],
    )
    assert bad.status_code == 422
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen()
    owner = listeners(lab, tmp_path)
    try:

        async def scenario() -> None:
            await owner.reconcile(lab["app"].state.sources.list())
            await owner.close()

        asyncio.run(scenario())
    finally:
        blocker.close()
    assert "in use" in (owner.status()["a"].error or "")
    lab["app"].state.listeners = owner
    listed = {s["source_id"]: s for s in lab["admin"].get("/api/sources", headers=lab["h"]).json()}
    assert listed["a"]["status"]["state"] == "error"
    assert "in use" in listed["a"]["status"]["error"]


def test_damaged_spool_is_set_aside_without_resyncing_into_message_bodies(
    lab: dict[str, Any], tmp_path: Path
) -> None:
    from app.ingest.listener import spool_record

    assert add(lab, "spooled", port=free_port(socket.SOCK_DGRAM)).status_code == 201
    folder = tmp_path / "data" / "spool" / "spooled"
    folder.mkdir(parents=True)
    forged = b'\n{"n":5,"ip":"6.6.6.6","t":0}\nforge\n'
    good = spool_record(LINE.encode(), "192.168.1.5", False)
    # A good record, then a header cut short by a crash, then a message that hides a
    # forged record and a negative length in its body.
    path = folder / "2099010100.syslog"
    path.write_bytes(
        good + b'{"n":99' + b"\n" + spool_record(forged + b'{"n":-40}\n', "192.168.1.5", False)
    )
    got = rows(lab, "spooled")
    assert [r[:2] for r in got] == [[LINE, "192.168.1.5"]]  # nothing forged, no hang
    assert not path.exists() and (folder / "2099010100.syslog.damaged").exists()
    listed = {s["source_id"]: s for s in lab["admin"].get("/api/sources", headers=lab["h"]).json()}
    assert "damaged" in (listed["spooled"]["status"]["error"] or "")


def test_a_short_write_leaves_no_half_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno
    import os
    from datetime import UTC, datetime

    from app.ingest import otlp

    spool = otlp.Spool(tmp_path, kind="syslog")
    now = datetime(2026, 10, 17, tzinfo=UTC)
    spool.append("s", [b"first\n"], now)
    real = os.write

    def short(fd: int, data: Any) -> int:
        real(fd, bytes(data)[:3])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(otlp.os, "write", short)
    with pytest.raises(OSError):
        spool.append("s", [b"second record\n"], now)
    (path,) = (tmp_path / "s").glob("*.syslog")
    assert path.read_bytes() == b"first\n"


def test_refused_senders_get_no_tls_handshake_and_memory_is_capped(
    lab: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest import listener as mod

    tls_port, udp = free_port(), free_port(socket.SOCK_DGRAM)
    assert (
        add(
            lab, "dmz_tls", protocol="tls", port=tls_port, allowed_senders=["10.0.0.0/8"]
        ).status_code
        == 201
    )
    assert add(lab, "busy", port=udp).status_code == 201
    monkeypatch.setattr(mod, "MAX_PENDING_BYTES", 2048)
    monkeypatch.setattr(mod, "FLUSH_EVERY_S", 30.0)  # nothing flushes during the test
    owner = listeners(lab, tmp_path)

    async def scenario() -> None:
        await owner.reconcile(lab["app"].state.sources.list())
        ctx = ssl.create_default_context(cafile=str(tmp_path / "tls" / "server.crt"))
        with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
            await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", tls_port, ssl=ctx), timeout=5
            )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(30):
                s.sendto(b"x" * 200, ("127.0.0.1", udp))
        await asyncio.sleep(0.3)
        st = owner.status()
        assert st["dmz_tls"].dropped_not_allowed == 1 and st["dmz_tls"].received == 0
        assert st["busy"].dropped_full > 0 and st["busy"].received < 30
        await owner.close()

    asyncio.run(scenario())
