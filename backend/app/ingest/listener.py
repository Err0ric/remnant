"""Native syslog listener: UDP, TCP, and TLS (ADR-0021).

Each enabled `kind: syslog` source owns one port. Messages from allowed senders are framed,
then appended to the source's spool as `{"n": <bytes>, "ip": "<sender>", "t": 0|1}\\n`
followed by the message and a newline; the ingest worker reads the spool through the
source's parser, so `raw` is each message exactly as received. Nothing here parses or
interprets message content.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.ingest.framer import StreamFramer
from app.ingest.listener_settings import SyslogSettings
from app.ingest.otlp import Spool, SpoolFullError
from app.ingest.records import Frame
from app.ingest.sources import SourceConfig

log = structlog.get_logger(__name__)

MAX_MESSAGE = 65_536  # bytes; longer messages are cut and flagged (row 3)
MAX_CONNECTIONS = 100  # open TCP or TLS connections per source (row 7)
IDLE_TIMEOUT_S = 600.0
READ_CHUNK = 65_536
MAX_PENDING = 20_000  # messages waiting for the next flush, per source
MAX_PENDING_BYTES = 32 * 1024 * 1024  # bytes held in memory per source, flush included
TLS_HANDSHAKE_S = 10.0
FLUSH_EVERY_S = 0.5
MAX_SENDERS = 200  # distinct sender addresses remembered per source
RETRY_FAILED_S = 60.0  # a listener that could not start is tried again after this

TlsFiles = Callable[[], tuple[Path, Path] | None]


@dataclass
class SenderSeen:
    count: int = 0
    last_seen: datetime | None = None
    allowed: bool = True


@dataclass
class ListenerStatus:
    protocol: str
    port: int
    listening: bool = False
    error: str | None = None
    received: int = 0
    dropped_not_allowed: int = 0
    dropped_full: int = 0
    connections: int = 0
    last_message_at: datetime | None = None
    senders: dict[str, SenderSeen] = field(default_factory=dict)


@dataclass
class _Running:
    settings: SyslogSettings
    status: ListenerStatus
    close: Callable[[], None]
    pending: list[bytes] = field(default_factory=list)
    pending_bytes: int = 0  # in `pending` plus the batch being written
    tls: ssl.SSLContext | None = None


def spool_record(message: bytes, sender: str, truncated: bool) -> bytes:
    head = json.dumps({"n": len(message), "ip": sender, "t": int(truncated)}, separators=(",", ":"))
    return head.encode() + b"\n" + message + b"\n"


class SyslogListeners:
    def __init__(
        self,
        spool_root: Path,
        host: str,
        tls_files: TlsFiles,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._spool = Spool(spool_root, kind="syslog")
        self._host = host
        self._tls_files = tls_files
        self._clock = clock
        self._running: dict[str, _Running] = {}
        self._failed: dict[str, tuple[SyslogSettings, ListenerStatus]] = {}
        self._failed_at: dict[str, datetime] = {}
        self._flusher: asyncio.Task[None] | None = None

    # --- lifecycle ------------------------------------------------------------------------

    async def reconcile(self, sources: list[SourceConfig]) -> None:
        """Start, stop, or restart listeners so they match the enabled syslog sources."""
        wanted = {
            s.source_id: s.syslog
            for s in sources
            if s.kind == "syslog" and s.enabled and s.syslog is not None
        }
        for sid in list(self._running):
            if wanted.get(sid) != self._running[sid].settings:
                await self._stop(sid)
        now = self._clock()
        for sid in list(self._failed):
            changed = wanted.get(sid) != self._failed[sid][0]
            stale = (now - self._failed_at.get(sid, now)).total_seconds() >= RETRY_FAILED_S
            if changed or stale:  # new settings, or the port may be free by now
                del self._failed[sid]
        for sid, settings in wanted.items():
            if sid not in self._running and sid not in self._failed:
                await self._start(sid, settings)
        if self._running and self._flusher is None:
            self._flusher = asyncio.create_task(self._flush_loop())

    async def close(self) -> None:
        for sid in list(self._running):
            await self._stop(sid)
        if self._flusher is not None:
            self._flusher.cancel()
            with suppress(asyncio.CancelledError):
                await self._flusher
            self._flusher = None

    def status(self) -> dict[str, ListenerStatus]:
        out = {sid: r.status for sid, r in self._running.items()}
        out.update({sid: st for sid, (_, st) in self._failed.items()})
        return out

    async def _start(self, sid: str, settings: SyslogSettings) -> None:
        status = ListenerStatus(protocol=settings.protocol, port=settings.port)
        loop = asyncio.get_running_loop()
        try:
            if settings.protocol == "udp":
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: _Udp(self, sid), local_addr=(self._host, settings.port)
                )
                close: Callable[[], None] = transport.close
            else:
                # TLS starts inside _stream, after the sender and connection checks, so
                # a host that may not send cannot make the server do handshakes.
                context = self._tls_context() if settings.protocol == "tls" else None
                server = await asyncio.start_server(
                    lambda r, w: self._stream(sid, r, w),
                    self._host,
                    settings.port,
                    limit=READ_CHUNK,
                )
                close = server.close
        except (OSError, ssl.SSLError, ValueError) as exc:
            status.error = _bind_error(settings, exc)
            self._failed[sid] = (settings, status)
            self._failed_at[sid] = self._clock()
            log.warning("syslog_listener.failed", source_id=sid, error=status.error)
            return
        status.listening = True
        self._running[sid] = _Running(
            settings=settings,
            status=status,
            close=close,
            tls=context if settings.protocol == "tls" else None,
        )
        log.info("syslog_listener.started", source_id=sid, protocol=settings.protocol)

    async def _stop(self, sid: str) -> None:
        running = self._running.pop(sid, None)
        if running is None:
            return
        running.close()
        await self._flush_one(sid, running)
        running.status.listening = False

    def _tls_context(self) -> ssl.SSLContext:
        files = self._tls_files()
        if files is None:
            raise ValueError("No certificate is available for TLS")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(files[0]), str(files[1]))
        return context

    # --- receiving ------------------------------------------------------------------------

    def _admit(self, sid: str, sender: str) -> bool:
        running = self._running.get(sid)
        if running is None:
            return False
        ok = running.settings.allows(sender)
        seen = running.status.senders.get(sender)
        if seen is None:
            if len(running.status.senders) >= MAX_SENDERS:
                oldest = min(
                    running.status.senders,
                    key=lambda k: (
                        running.status.senders[k].last_seen or datetime.min.replace(tzinfo=UTC)
                    ),
                )
                del running.status.senders[oldest]
            seen = running.status.senders[sender] = SenderSeen(allowed=ok)
        if not ok:
            # Refused messages (UDP) or connections (TCP, TLS) from this address.
            seen.count += 1
            seen.last_seen = self._clock()
            running.status.dropped_not_allowed += 1
        return ok

    def _accept(self, sid: str, sender: str, frame: Frame) -> None:
        running = self._running.get(sid)
        if running is None or not frame.data:
            return
        record = spool_record(frame.data, sender, frame.truncated)
        if (
            len(running.pending) >= MAX_PENDING
            or running.pending_bytes + len(record) > MAX_PENDING_BYTES
        ):
            running.status.dropped_full += 1
            return
        running.pending.append(record)
        running.pending_bytes += len(record)
        now = self._clock()
        running.status.received += 1
        running.status.last_message_at = now
        seen = running.status.senders.get(sender)
        if seen is not None:
            seen.count += 1
            seen.last_seen = now

    def datagram(self, sid: str, data: bytes, sender: str) -> None:
        # Counted per datagram, which is per message for UDP.
        if not self._admit(sid, sender):
            return
        if data.endswith(b"\n"):
            data = data[:-2] if data.endswith(b"\r\n") else data[:-1]
        cut = len(data) > MAX_MESSAGE
        self._accept(sid, sender, Frame(data[:MAX_MESSAGE], truncated=cut))

    async def _stream(
        self, sid: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        sender = str(peer[0]) if peer else "unknown"
        running = self._running.get(sid)
        if running is None or running.status.connections >= MAX_CONNECTIONS:
            if running is not None:
                running.status.dropped_full += 1
            writer.close()
            return
        if not self._admit(sid, sender):
            writer.close()
            return
        running.status.connections += 1
        framer = StreamFramer(MAX_MESSAGE)
        try:
            if running.tls is not None:
                await writer.start_tls(running.tls, ssl_handshake_timeout=TLS_HANDSHAKE_S)
            while True:
                chunk = await asyncio.wait_for(reader.read(READ_CHUNK), IDLE_TIMEOUT_S)
                if not chunk:
                    break
                for frame in framer.feed(chunk):
                    self._accept(sid, sender, frame)
            for frame in framer.close():
                self._accept(sid, sender, frame)
        except (TimeoutError, OSError, ssl.SSLError):
            pass  # idle, reset, or a failed handshake: the connection just ends
        finally:
            running.status.connections -= 1
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    # --- spooling -------------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_EVERY_S)
            for sid, running in list(self._running.items()):
                await self._flush_one(sid, running)

    async def _flush_one(self, sid: str, running: _Running) -> None:
        if not running.pending:
            return
        chunk, running.pending = running.pending, []
        size = sum(len(r) for r in chunk)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._spool.append, sid, chunk, self._clock())
        except SpoolFullError:
            running.status.dropped_full += len(chunk)
        except OSError as exc:
            running.status.dropped_full += len(chunk)
            log.warning("syslog_listener.spool_failed", source_id=sid, error=type(exc).__name__)
        finally:
            running.pending_bytes -= size


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, owner: SyslogListeners, sid: str) -> None:
        self._owner, self._sid = owner, sid

    def datagram_received(self, data: bytes, addr: tuple[str | int, ...]) -> None:
        self._owner.datagram(self._sid, data, str(addr[0]))


def _bind_error(settings: SyslogSettings, exc: Exception) -> str:
    if isinstance(exc, OSError) and exc.errno in (13, 98, 48):
        reason = "in use" if exc.errno in (98, 48) else "not allowed"
        return f"Cannot listen on {settings.protocol.upper()} port {settings.port}: {reason}"
    return f"Cannot start the {settings.protocol.upper()} listener: {str(exc)[:200]}"
