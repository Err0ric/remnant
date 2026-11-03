"""Named ingest tokens per deployment for OTLP sources (owner, 2026-10-29; SPEC D127).

A plugin package carries a working credential, so each deployment ("pilot", "all
Windows") gets its own token: revoking one cuts off that deployment only. The token is
shown never: only its name and prefix. Its SHA-256 finds it at the receiver; a copy sealed
with the install key lets a later download (a new plugin version) carry the same token.
The single token a source had before (`sources.otlp_token_hash`) keeps working as
"Earlier token" until revoked.
"""

from __future__ import annotations

import builtins
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.errors import NotFoundError, SourceRejectedError
from app.ingest.sources import hash_token
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox

LEGACY = "earlier"  # token id of a source's pre-D127 token
MAX_HOSTS_SHOWN = 50
_TOUCH_EVERY_S = 300.0  # write last-used and host rows at most this often per pair
_ERROR_EVERY_S = 10.0  # write a token's last error at most this often
UNKNOWN_KEPT = 20  # refused tokens that match none of ours, shown by prefix


@dataclass(slots=True)
class Machine:
    host: str
    last_seen: str


@dataclass(slots=True)
class Unknown:
    """A token the receiver refused that matches none of this server's (D170): shown by
    its first 8 characters only, when it has our shape, with the sending address."""

    prefix: str
    client: str
    first_at: str
    last_at: str
    count: int


@dataclass(slots=True)
class Token:
    token_id: str
    source_id: str
    name: str
    prefix: str
    created_at: str | None
    created_by: str | None
    revoked_at: str | None
    last_used_at: str | None
    devices: int = 0
    hosts: list[str] = field(default_factory=list)
    downloadable: bool = True  # False for the earlier token: never sealed
    machines: list[Machine] = field(default_factory=list)  # newest first, with last seen
    last_error: str | None = None  # why the receiver last refused this token
    last_error_at: str | None = None


@dataclass(frozen=True, slots=True)
class Match:
    source_id: str
    token_id: str
    revoked: bool


class OtlpTokens:
    def __init__(self, meta: MetaDB, box: SecretBox) -> None:
        self._meta = meta
        self._box = box
        self._touched: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()
        self._errors_at: dict[str, float] = {}
        self._unknown: OrderedDict[tuple[str, str], Unknown] = OrderedDict()

    def create(self, source_id: str, name: str, user_id: str | None) -> tuple[Token, str]:
        """A new token for an OTLP source; the plain token is returned once."""
        token = "rmt_" + secrets.token_urlsafe(32)
        tid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT kind FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("No such source")
            if row["kind"] != "otlp":
                raise SourceRejectedError("Ingest tokens are for OTLP sources only")
            con.execute(
                "INSERT INTO otlp_tokens (token_id, source_id, name, prefix, token_hash, sealed,"
                " created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, source_id, name, token[:8], hash_token(token), self._box.encrypt(token),
                 now, user_id),
            )  # fmt: skip
        return Token(tid, source_id, name, token[:8], now, user_id, None, None), token

    def plain(self, token_id: str) -> tuple[str, str]:
        """(source id, token) of a live token, for a download; never sent to the browser."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT source_id, sealed FROM otlp_tokens"
                " WHERE token_id = ? AND revoked_at IS NULL",
                (token_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("No such token, or it was revoked")
        return str(row["source_id"]), self._box.decrypt(str(row["sealed"]))

    def revoke(self, token_id: str, source_id: str, user_id: str | None) -> Token:
        now = datetime.now(UTC).isoformat()
        with self._meta.connect() as con:
            if token_id == LEGACY:
                con.execute(
                    "UPDATE sources SET otlp_token_hash = NULL WHERE source_id = ?", (source_id,)
                )
            else:
                cur = con.execute(
                    "UPDATE otlp_tokens SET revoked_at = ?, revoked_by = ?"
                    " WHERE token_id = ? AND source_id = ? AND revoked_at IS NULL",
                    (now, user_id, token_id, source_id),
                )
                if cur.rowcount == 0:
                    raise NotFoundError("No such token, or it was already revoked")
        found = [t for t in self.list(source_id) if t.token_id == token_id]
        return found[0] if found else Token(token_id, source_id, "", "", None, None, now, None)

    def list(self, source_id: str | None = None) -> list[Token]:
        """Every token, newest first, with the hosts that sent with it."""
        where, args = ("WHERE source_id = ?", (source_id,)) if source_id else ("", ())
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT token_id, source_id, name, prefix, created_at, created_by, revoked_at,"  # noqa: S608  # fixed text
                f" last_used_at, last_error, last_error_at FROM otlp_tokens {where}"
                " ORDER BY created_at DESC",
                args,
            ).fetchall()
            hosts: dict[str, list[str]] = {}
            machines: dict[str, list[Machine]] = {}
            for h in con.execute(
                "SELECT token_id, host, last_seen FROM otlp_token_hosts ORDER BY last_seen DESC"
            ).fetchall():
                hosts.setdefault(str(h["token_id"]), []).append(str(h["host"]))
                machines.setdefault(str(h["token_id"]), []).append(
                    Machine(str(h["host"]), str(h["last_seen"]))
                )
            legacy = con.execute(
                "SELECT source_id FROM sources"  # noqa: S608  # fixed text
                " WHERE kind = 'otlp' AND otlp_token_hash IS NOT NULL"
                + (" AND source_id = ?" if source_id else ""),
                args,
            ).fetchall()
        out = [
            Token(
                str(r["token_id"]), str(r["source_id"]), str(r["name"]), str(r["prefix"]),
                r["created_at"], r["created_by"], r["revoked_at"], r["last_used_at"],
                devices=len(hosts.get(str(r["token_id"]), [])),
                hosts=hosts.get(str(r["token_id"]), [])[:MAX_HOSTS_SHOWN],
                machines=machines.get(str(r["token_id"]), [])[:MAX_HOSTS_SHOWN],
                last_error=r["last_error"], last_error_at=r["last_error_at"],
            )
            for r in rows
        ]  # fmt: skip
        for r in legacy:
            key = f"{LEGACY}:{r['source_id']}"
            out.append(
                Token(LEGACY, str(r["source_id"]), "Earlier token", "rmt_", None, None, None, None,
                      devices=len(hosts.get(key, [])), hosts=hosts.get(key, [])[:MAX_HOSTS_SHOWN],
                      downloadable=False)
            )  # fmt: skip
        return out

    def match(self, token: str) -> Match | None:
        """The source and token id a presented token belongs to, revoked or not."""
        if not token.startswith("rmt_") or len(token) > 200:
            return None
        digest = hash_token(token)
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT source_id, token_id, revoked_at FROM otlp_tokens WHERE token_hash = ?",
                (digest,),
            ).fetchone()
            if row is not None:
                return Match(
                    str(row["source_id"]), str(row["token_id"]), row["revoked_at"] is not None
                )
            legacy = con.execute(
                "SELECT source_id FROM sources WHERE otlp_token_hash = ? AND kind = 'otlp'",
                (digest,),
            ).fetchone()
        return Match(str(legacy["source_id"]), LEGACY, False) if legacy else None

    def failed(self, match: Match | None, prefix: str | None, client: str, reason: str) -> None:
        """Record why the receiver refused a request (D170): on the named token when the
        token is one of ours (at most every 10 seconds per token), else among recent
        unknown tokens by prefix. Never the token itself."""
        now = datetime.now(UTC).isoformat()
        if match is not None and match.token_id != LEGACY:
            now_m = time.monotonic()
            with self._lock:
                if now_m - self._errors_at.get(match.token_id, -1e9) < _ERROR_EVERY_S:
                    return
                self._errors_at[match.token_id] = now_m
            with self._meta.connect() as con:
                con.execute(
                    "UPDATE otlp_tokens SET last_error = ?, last_error_at = ? WHERE token_id = ?",
                    (reason[:200], now, match.token_id),
                )
            return
        if match is not None or not prefix:
            return
        key = (prefix[:8], client[:64])
        with self._lock:
            had = self._unknown.pop(key, None)
            if had is None:
                had = Unknown(key[0], key[1], now, now, 0)
            had.last_at, had.count = now, had.count + 1
            self._unknown[key] = had
            while len(self._unknown) > UNKNOWN_KEPT:
                self._unknown.popitem(last=False)

    def unknown(self) -> builtins.list[Unknown]:
        """Refused tokens that match none of ours, newest first."""
        with self._lock:
            return [*reversed(self._unknown.values())]

    def seen(self, match: Match, hosts: set[str]) -> None:
        """Record that this token sent, and from which hosts (at most every 5 minutes)."""
        key = match.token_id if match.token_id != LEGACY else f"{LEGACY}:{match.source_id}"
        now_m = time.monotonic()
        due: list[str] = []
        with self._lock:
            for h in ["", *sorted(hosts)[:20]]:
                k = (key, h)
                if now_m - self._touched.get(k, -1e9) >= _TOUCH_EVERY_S:
                    self._touched[k] = now_m
                    due.append(h)
        if not due:
            return
        now = datetime.now(UTC).isoformat()
        with self._meta.connect() as con:
            if "" in due and match.token_id != LEGACY:
                con.execute(
                    "UPDATE otlp_tokens SET last_used_at = ? WHERE token_id = ?", (now, key)
                )
            for h in due:
                if h:
                    con.execute(
                        "INSERT INTO otlp_token_hosts (token_id, host, last_seen) VALUES (?, ?, ?)"
                        " ON CONFLICT (token_id, host)"
                        " DO UPDATE SET last_seen = excluded.last_seen",
                        (key, h[:200], now),
                    )
