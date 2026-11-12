"""People in stored AI Watch alert items, coded by where they stand (D242, ADR-0029 C6).

An AI Watch item stores no name: each person is a reference `{p:<digest>}` of one exact
spelling (app.alerts.person_refs), and that spelling is kept in the item's people, so
reading the item puts its text back byte for byte. A person is coded by the structure
of each key and line, never by searching the text for a name:

- keys (subject, ref id, group): the part right after `sensitive:`, `account:`,
  `personal:`, or `agent:cc|`, whole, when it is a person and not a machine the item
  proves is one (`names_in`). The same key always codes the same way, whoever else the
  item names, so dedup, groups, and mutes keep matching.
- lines (title, detail, why, changes): each element of the lists AI Watch writes people
  into (an agent's owners, who used a service or MCP server, the person a title is
  about), whole.

Machine, host, and client names (`mcp|ALICE-PC|Claude Desktop`) are never touched, even
when they hold a name.

New raises store codes only once a start rewrite has completed: one stored flag
(`one_time_fixes` row `alerts.person_codes`), set when the rewrite completes and never
cleared, so a key is never stored named after it was stored coded. A failed backup at a
later start leaves the flag set and only that start's rewrite waits for the next start.
The flag's value is the code of KEY_CHECK, so scripts/restore_alert_text.py can tell
whether its key file is the one the codes were made with.
"""

import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from app.ai.alert_mask import _OWNER_PATTERNS, names_in
from app.alerts.person_refs import REF, PersonRefs
from app.meta.db import MetaDB

FLAG = "alerts.person_codes"
KEY_CHECK = "remnant-key-check"  # its code is stored with FLAG (scripts/restore_alert_text.py)
BACKUP_PREFIX = "meta-before-alert-rewrite-"
KEY_HEADS = ("sensitive:", "account:", "personal:", "agent:cc|")
# The person a title or line is about, as AI Watch writes it (app.ai.watch).
_LISTS = (
    *_OWNER_PATTERNS,
    re.compile(r"^Sensitive data to AI: (.+)$"),
    re.compile(r"^Personal Claude account (\S+) on "),
    re.compile(r"^AI agent: blocked or failed calls, (.+)$"),
    re.compile(r" by Claude Code for (.+)$"),
)


class Coder:
    """Codes one item's keys and lines, from its subject, people, lines, and devices."""

    def __init__(
        self,
        refs: PersonRefs,
        subject: str,
        people: Iterable[str],
        texts: Iterable[str | None],
        devices: Iterable[str] = (),
    ) -> None:
        self._refs = refs
        self.people = [str(p) for p in people]
        # Only names the people field stores exactly as given (`raise_item` strips them and
        # keeps 256 characters) are coded, so each reads back; any other stays as it is and
        # is masked when read (D242).
        self.persons = {
            n
            for n in names_in(subject, self.people, texts, devices)
            if not REF.search(n) and n == n.strip()[:256]
        }
        who = _slot(subject)
        self._who = who if who in self.persons else None

    def all_people(self) -> list[str]:
        """The item's people with every person it codes, each in its exact spelling."""
        return self.people + sorted(self.persons - set(self.people))

    def key(self, key: str | None) -> str | None:
        """`key` with its person part, whole, as that person's reference."""
        who = self._who
        if key is None or who is None:
            return key
        for head in KEY_HEADS:
            rest = key[len(head) :] if key.startswith(head) else None
            if rest is not None and (rest == who or rest.startswith(who + ":")):
                return head + self._refs.ref(who) + rest[len(who) :]
        return key

    def text(self, text: str | None) -> str | None:
        """`text` with each person in a list AI Watch writes people into as a reference."""
        if not text or not self.persons:
            return text
        for pattern in _LISTS:
            text = pattern.sub(self._code_group, text)
        return text

    def _code_group(self, m: re.Match[str]) -> str:
        parts = []
        for part in m.group(1).split(", "):
            name = part.strip().removesuffix(" and more")  # as names_in reads it
            if name in self.persons:
                part = part.replace(name, self._refs.ref(name), 1)
            parts.append(part)
        whole, at = m.group(0), m.start()
        return whole[: m.start(1) - at] + ", ".join(parts) + whole[m.end(1) - at :]


def _slot(subject: str) -> str | None:
    for head in KEY_HEADS:
        if subject.startswith(head):
            return subject[len(head) :]
    return None


def codes_on(meta: MetaDB) -> bool:
    """Do new AI Watch items store codes (the start rewrite completed)?"""
    with meta.connect() as con:
        return (
            con.execute("SELECT 1 FROM one_time_fixes WHERE fix_id = ?", (FLAG,)).fetchone()
            is not None
        )


def backup_copy(con: sqlite3.Connection, folder: Path, at: datetime) -> Path:
    """Copy the database `con` reads into `folder` as
    `meta-before-alert-rewrite-<UTC yyyymmddThhmmssZ>.sqlite` with SQLite's online
    backup, 0600, in a folder made 0700 when missing; written beside it and linked in
    place, so a crash mid-copy leaves no file and an existing copy is never overwritten
    (a second one in the same second gets `-2`)."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = f"{BACKUP_PREFIX}{at.strftime('%Y%m%dT%H%M%SZ')}"
    tmp = folder / f".{stamp}.tmp"
    tmp.unlink(missing_ok=True)
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    os.chmod(tmp, 0o600)
    try:
        dst = sqlite3.connect(tmp)
        try:
            con.backup(dst)
        finally:
            dst.close()
        n = 1
        while True:
            path = folder / f"{stamp}{'' if n == 1 else f'-{n}'}.sqlite"
            try:
                os.link(tmp, path)
            except FileExistsError:
                n += 1
                continue
            except OSError:  # no hard links here: take the name, then move the copy in
                try:
                    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                except FileExistsError:
                    n += 1
                    continue
                os.replace(tmp, path)
            return path
    finally:
        tmp.unlink(missing_ok=True)  # a part copy is no backup; give its space back


def store_without_names(
    meta: MetaDB,
    refs: PersonRefs,
    backup: Callable[[sqlite3.Connection], bool],
    now: str,
) -> tuple[int, int]:
    """At every start (D242): AI Watch items and their mutes stored with names (by an
    older version, or while this rewrite waited) are coded, and names that were only in
    their text move into their people. Kept items, whose coded ref id or group would clash
    with another item's, are found by a dry run first and left as they were (masked when
    read). `backup` runs first when anything else is to change; when it returns False
    nothing is changed, the flag stays as it was (unset at a first start, so new raises
    keep names too), and (0, 0) is returned. Otherwise the flag is set. Idempotent.
    Returns (rewritten, kept)."""
    updates: list[tuple[str, list[str | None], str | None, list[str]]] = []
    coders: dict[str, Coder] = {}  # stored subject -> its coder, for its mutes
    with meta.connect() as con:
        rows = con.execute(
            "SELECT item_id, subject, ref_id, title, detail, why, entity, changes, people,"
            " devices FROM alert_items WHERE kind = 'ai_watch' ORDER BY created_at, rowid"
        ).fetchall()
        for r in rows:
            log = json.loads(r["changes"]) if r["changes"] else None
            lines = [str(x) for x in log.get("lines", [])] if isinstance(log, dict) else []
            c = Coder(
                refs, r["subject"], json.loads(r["people"] or "[]"),
                [r["title"], r["detail"], r["why"], *lines], json.loads(r["devices"] or "[]"),
            )  # fmt: skip
            coders.setdefault(r["subject"], c)
            old = [r["subject"], r["ref_id"], r["entity"], r["title"], r["detail"], r["why"]]
            new = [c.key(x) for x in old[:3]] + [c.text(x) for x in old[3:]]
            new_lines = [c.text(x) or "" for x in lines]
            people = c.all_people()
            if new == old and new_lines == lines and people == c.people:
                continue
            if isinstance(log, dict):
                log["lines"] = new_lines
            changes = json.dumps(log) if isinstance(log, dict) else r["changes"]
            updates.append((r["item_id"], new, changes, people))
        mutes: list[tuple[str, str | None, str | None]] = []
        for m in con.execute(
            "SELECT mute_id, subject, title FROM alert_mutes WHERE kind = 'ai_watch'"
        ).fetchall():
            mc = coders.get(m["subject"])  # a mute matches its items' subject as stored
            if mc is not None and (mc.key(m["subject"]), mc.text(m["title"])) != (
                m["subject"], m["title"],
            ):  # fmt: skip
                mutes.append((m["mute_id"], mc.key(m["subject"]), mc.text(m["title"])))
        con.execute("SAVEPOINT dry_run")  # which rows clash, so they never cause a backup
        clashes = _apply(con, updates)
        con.execute("ROLLBACK TO dry_run")
        con.execute("RELEASE dry_run")
        updates = [u for u in updates if u[0] not in clashes]
        if (updates or mutes) and not backup(con):
            return 0, 0
        late = _apply(con, updates)  # none expected: the same rows, in the same order
        rewritten, kept = len(updates) - len(late), len(clashes | late)
        for mute_id, subject, title in mutes:
            con.execute(
                "UPDATE alert_mutes SET subject = ?, title = ? WHERE mute_id = ?",
                (subject, title, mute_id),
            )
        # The key check: the code of a fixed string, so a restore can tell the key the
        # codes were made with without any code left to decode. A flag set before it
        # existed gets it now (the key the server reads codes with).
        con.execute(
            "INSERT INTO one_time_fixes (fix_id, applied_at, changed, value) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (fix_id) DO UPDATE SET value = excluded.value WHERE value IS NULL",
            (FLAG, now, rewritten, refs.ref(KEY_CHECK)),
        )
    return rewritten, kept


def _apply(
    con: sqlite3.Connection, updates: list[tuple[str, list[str | None], str | None, list[str]]]
) -> set[str]:
    """Write `updates`; returns the item ids whose coded ref id or group clashed."""
    clashes: set[str] = set()
    for item_id, new, changes, people in updates:
        try:  # one statement: a clash undoes only this row
            con.execute(
                "UPDATE alert_items SET subject = ?, ref_id = ?, entity = ?, title = ?,"
                " detail = ?, why = ?, changes = ?, people = ? WHERE item_id = ?",
                (*new, changes, json.dumps(people), item_id),
            )
        except sqlite3.IntegrityError:
            clashes.add(item_id)
    return clashes
