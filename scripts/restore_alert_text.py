#!/usr/bin/env python3
"""Turn the codes in AI watch alert text back into names, in place (D242).

The version that stores no names in AI watch alerts keeps each person in an alert's
People field and writes a code such as {p:3f2a9c0b1d4e5f60} in its place in the
alert's subject, reference, group, title, details, reason, and change lines, and in
its mutes' subject and title. The code is a keyed hash of that exact spelling, with a
key derived from the install key (the data folder's .key file), as
app.alerts.person_refs makes it. An older version shows those codes as they are.

After a rollback to such an older version, this script finds, for each code in each AI
watch alert, the name in that alert's own People whose code it is, and writes the name
in place of the code. A mute's codes are found from the People of the alerts with its
subject. Nothing else changes: People, counts, states, notes, change lines added since,
alerts raised since, other alerts, read positions, and the lake ledger stay as they
are. The run adds one row to the audit log (`alerts.restore_text`, counts only, chained
as the server chains its rows) unless it is a dry run or changes nothing.

With --backup (a backups/meta-before-alert-rewrite-<time>.sqlite copy), a code that no
name in the alert's People matches is also looked for in the People that alert had in
the copy; nothing else is taken from the copy. A code still matched by no one stays and
is counted, as is an alert whose decoded reference or group another alert now holds (the
older version raised it again after the rollback): that alert keeps all its codes.

Before changing anything it checks the key. The server stores the code of a fixed
string with its `alerts.person_codes` flag (one_time_fixes); when the key file makes a
different code, it is not the key the alerts were coded with, and nothing changes. This
check does not depend on what is left to decode. A database coded before the server
stored that value is checked by matching instead: when codes are left and not one of
them matches a name, nothing changes; when some match, the key is right and the run
stores the value, so a later run checks it the first way.

Stop the service first. Standard library only, so it runs with the system python3:

    sudo -u remnant python3 restore_alert_text.py \\
        --meta /var/lib/remnant/meta.sqlite \\
        [--key /var/lib/remnant/.key] \\
        [--backup /var/lib/remnant/backups/meta-before-alert-rewrite-<time>.sqlite] \\
        [--dry-run]

One transaction; --dry-run counts and changes nothing. Running it again is safe: the
second run decodes what it can (more, with --backup), counts again what no name matches,
and changes nothing else. It prints counts only, never names.
Runs on python3 3.8 and later.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

REF = re.compile(r"\{p:[0-9a-f]{16}\}")
FLAG = "alerts.person_codes"  # as app.ai.alert_codes stores it
KEY_CHECK = "remnant-key-check"
ITEM_TEXT = ("subject", "ref_id", "entity", "title", "detail", "why", "changes")
MUTE_TEXT = ("subject", "title")
GENESIS = "0" * 64  # as app.core.chain
if TYPE_CHECKING:  # a runtime alias would need typing.List on 3.8
    Plan = list[tuple[str, dict[str, object], bool]]  # (id, columns to write, a code stays)


class WrongKeyError(Exception):
    """The key file does not produce the codes stored."""


class Codes:
    """Codes of names, as app.alerts.person_refs.PersonRefs.ref makes them."""

    def __init__(self, install_key: bytes) -> None:
        self._key = hmac.new(install_key, b"alert-people-v1", hashlib.sha256).digest()

    def ref(self, name: str) -> str:
        return "{p:" + hmac.new(self._key, name.encode(), hashlib.sha256).hexdigest()[:16] + "}"

    def known(self, people: object) -> dict[str, str]:
        return {self.ref(p): p for p in _people(people)}


def _people(raw: object) -> list[str]:
    try:
        values = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        return []
    return [str(v) for v in values] if isinstance(values, list) else []


def _coded(values: dict[str, object]) -> bool:
    return any(isinstance(v, str) and REF.search(v) for v in values.values())


def _decode(
    text: object, known: dict[str, str], extra: dict[str, str], in_json: bool
) -> tuple[object, int, int]:
    """`text` with each code that a name in `known` (else in `extra`) stands for, as that
    name; in a JSON column, as JSON string content. Returns (text, decoded, left)."""
    if not isinstance(text, str) or "{p:" not in text:
        return text, 0, 0
    counts = [0, 0]

    def one(m: re.Match[str]) -> str:
        name = known.get(m.group(0), extra.get(m.group(0)))
        if name is None:
            counts[1] += 1
            return m.group(0)
        counts[0] += 1
        return json.dumps(name)[1:-1] if in_json else name

    return REF.sub(one, text), counts[0], counts[1]


def _plan(con: sqlite3.Connection, codes: Codes, with_backup: bool) -> tuple[Plan, Plan, int]:
    """Items and mutes to write; and how many codes found a name (for the key check)."""
    rows = con.execute(
        "SELECT item_id, " + ", ".join(ITEM_TEXT) + ", people FROM main.alert_items"  # noqa: S608  # fixed column names
        " WHERE kind = 'ai_watch'"
    ).fetchall()
    old_people: dict[str, object] = {}
    if with_backup:
        old_people = dict(
            con.execute("SELECT item_id, people FROM old.alert_items WHERE kind = 'ai_watch'")
        )
    matched = 0
    items: Plan = []
    by_subject: dict[str, dict[str, str]] = {}  # a mute's names: its subject's items' people
    for row in rows:
        item_id, values = row[0], dict(zip(ITEM_TEXT, row[1:-1]))  # noqa: B905  # strict needs 3.10
        known, extra = codes.known(row[-1]), codes.known(old_people.get(item_id))
        for_mutes = by_subject.setdefault(str(values["subject"]), {})
        for_mutes.update(extra)
        for_mutes.update(known)
        if not _coded(values):
            continue
        put: dict[str, object] = {}
        left = 0
        for col, value in values.items():
            new, done, kept = _decode(value, known, extra, col == "changes")
            matched, left = matched + done, left + kept
            if done:
                put[col] = new
        items.append((item_id, put, left > 0))
    mutes: Plan = []
    for row in con.execute(
        "SELECT mute_id, subject, title FROM main.alert_mutes WHERE kind = 'ai_watch'"
    ).fetchall():
        mute_id, values = row[0], dict(zip(MUTE_TEXT, row[1:]))  # noqa: B905  # strict needs 3.10
        if not _coded(values):
            continue
        names = by_subject.get(str(values["subject"]), {})
        put, left = {}, 0
        for col, value in values.items():
            new, done, kept = _decode(value, names, {}, False)
            matched, left = matched + done, left + kept
            if done:
                put[col] = new
        mutes.append((mute_id, put, left > 0))
    return items, mutes, matched


def _audit_hash(prev: str, row: tuple[object, ...]) -> str:
    """As app.core.chain.audit_hash: one audit row, chained to the row before."""
    text = json.dumps([prev, *[("" if v is None else str(v)) for v in row]], separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _os_user() -> str | None:
    try:
        return getpass.getuser()
    except (OSError, KeyError):  # no login name for this process
        return None


def _audit(con: sqlite3.Connection, detail: dict[str, object]) -> None:
    """One audit row, as app.meta.audit.AuditLog.write writes it (CLAUDE.md rule 14), in
    the transaction that holds the write lock (BEGIN IMMEDIATE), so nothing chains from
    the same row in between."""
    content = (
        datetime.now(timezone.utc).isoformat(),  # noqa: UP017  # datetime.UTC needs 3.11
        None,  # no app user: an administrator ran it on the server
        "alerts.restore_text",
        "success",
        None,
        json.dumps(detail, default=str, separators=(",", ":")),
    )
    prev = con.execute(
        "SELECT chain_hash FROM main.audit_log WHERE chain_hash IS NOT NULL"
        " ORDER BY audit_id DESC LIMIT 1"
    ).fetchone()
    con.execute(
        "INSERT INTO main.audit_log (ts, user_id, action, outcome, ip, detail, chain_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (*content, _audit_hash(prev[0] if prev else GENESIS, content)),
    )


def _stored_check(con: sqlite3.Connection) -> tuple[bool, str | None]:
    """(can the flag row hold a value, the key check stored there)."""
    try:
        row = con.execute("SELECT value FROM one_time_fixes WHERE fix_id = ?", (FLAG,)).fetchone()
    except sqlite3.OperationalError:  # no table or no value column: coded before the check
        return False, None
    return row is not None, (row[0] if row and isinstance(row[0], str) else None)


def restore(
    meta: Path, key: bytes, backup: Path | None = None, dry_run: bool = False
) -> dict[str, int]:
    """Decode in one transaction. The backup, when given, is attached read-only and
    immutable: a finished copy nothing writes to, so older SQLite reads it without making
    -wal or -shm files beside it. Raises WrongKeyError (changing nothing) when the stored
    key check differs from this key's, or, with none stored, when codes are left and the
    key matches none of them. Returns counts: items and mutes decoded, items left with
    codes because another alert holds their decoded reference or group, items and mutes
    with a code no name matched, and `unchecked` (1 when no key check was stored)."""
    codes = Codes(key)
    con = sqlite3.connect(
        "file:" + quote(str(meta.resolve())), uri=True, isolation_level=None, timeout=30
    )
    try:
        if backup is not None:
            con.execute(
                "ATTACH DATABASE ? AS old",
                ("file:" + quote(str(backup.resolve())) + "?mode=ro&immutable=1",),
            )
        con.execute("BEGIN IMMEDIATE")
        try:
            check = codes.ref(KEY_CHECK)
            can_store, stored = _stored_check(con)
            if stored is not None and not hmac.compare_digest(stored, check):
                raise WrongKeyError
            items, mutes, matched = _plan(con, codes, backup is not None)
            if stored is None and (items or mutes) and not matched:
                raise WrongKeyError
            counts = dict.fromkeys(
                ("items", "items_clash", "items_unmatched", "mutes", "mutes_unmatched"), 0
            )
            counts["unchecked"] = int(stored is None)
            stores_check = stored is None and bool(matched) and can_store
            if stores_check:  # the key is proven: keep its check
                con.execute(
                    "UPDATE main.one_time_fixes SET value = ? WHERE fix_id = ?", (check, FLAG)
                )
            for item_id, put, left in items:
                counts["items_unmatched"] += left
                if not put:
                    continue
                sets = ", ".join(f"{c} = ?" for c in put)
                try:  # one statement: a clash undoes only this row
                    con.execute(
                        f"UPDATE main.alert_items SET {sets} WHERE item_id = ?",  # noqa: S608  # fixed columns
                        (*put.values(), item_id),
                    )
                    counts["items"] += 1
                except sqlite3.IntegrityError:
                    counts["items_clash"] += 1
            for mute_id, put, left in mutes:
                counts["mutes_unmatched"] += left
                if not put:
                    continue
                sets = ", ".join(f"{c} = ?" for c in put)
                con.execute(
                    f"UPDATE main.alert_mutes SET {sets} WHERE mute_id = ?",  # noqa: S608  # fixed columns
                    (*put.values(), mute_id),
                )
                counts["mutes"] += 1
            if not dry_run and (counts["items"] or counts["mutes"] or stores_check):
                _audit(
                    con,
                    {  # counts only, never names; os_user is the server account that ran it
                        "alerts_decoded": counts["items"],
                        "mutes_decoded": counts["mutes"],
                        "alerts_left_with_codes": counts["items_unmatched"],
                        "mutes_left_with_codes": counts["mutes_unmatched"],
                        "alerts_clashed": counts["items_clash"],
                        "key_check_stored": stores_check,
                        "backup_used": backup is not None,
                        "os_user": _os_user(),
                    },
                )
            con.execute("ROLLBACK" if dry_run else "COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        return counts
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--meta", type=Path, required=True, help="path to meta.sqlite")
    parser.add_argument(
        "--key", type=Path, help="the install key file (default: .key beside meta.sqlite)"
    )
    parser.add_argument(
        "--backup",
        type=Path,
        help="a meta-before-alert-rewrite-<time>.sqlite copy, for names no longer in People",
    )
    parser.add_argument("--dry-run", action="store_true", help="show the counts, change nothing")
    args = parser.parse_args(argv)
    key_file = args.key or args.meta.parent / ".key"
    for what, path in (("Database", args.meta), ("Key file", key_file), ("Backup", args.backup)):
        if path is not None and not path.is_file():
            print(f"{what} not found: {path}. Nothing was changed.", file=sys.stderr)
            return 2
    try:
        counts = restore(args.meta, key_file.read_bytes().strip(), args.backup, args.dry_run)
    except WrongKeyError:
        print(
            f"The key file {key_file} is not the key these alerts were coded with"
            " (use the .key of that data folder)."
            " Nothing was changed.",
            file=sys.stderr,
        )
        return 3
    except (OSError, sqlite3.Error) as exc:
        print(f"Restore failed ({type(exc).__name__}). Nothing was changed.", file=sys.stderr)
        return 1
    verb = "Would put back" if args.dry_run else "Put back"
    print(f"{verb} names in AI watch alerts: {counts['items']}; mutes: {counts['mutes']}.")
    if counts["items_clash"]:
        print(
            f"Left with codes: {counts['items_clash']} alerts (another alert now has the same"
            " reference or group)."
        )
    if counts["items_unmatched"] or counts["mutes_unmatched"]:
        hint = " or in the copy)." if args.backup else "; --backup may find it)."
        print(
            f"Left with codes: {counts['items_unmatched']} alerts and"
            f" {counts['mutes_unmatched']} mutes (a code matches no name in their People{hint}"
        )
    if counts["unchecked"]:
        print(
            "Note: this database has no stored key check (coded before the server kept one);"
            " the key was checked by matching codes to names.",
            file=sys.stderr,
        )
    if args.dry_run:
        print("Dry run: nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
