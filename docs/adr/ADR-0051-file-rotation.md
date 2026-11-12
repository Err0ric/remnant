# ADR-0051: One read position per file, not per path

Status: **Draft** 2026-11-12, for the owner's review. Nothing here is built. Follows audit 2026-11 finding H5 and the parked fix (#529). If accepted it amends the SPEC 3.5 "Idempotency" row and gets a decision row. Not AI-facing: no ATLAS mapping; the one threat it touches is a file swapped in under a source (SPEC 5 rule 6, row 9 below).

## Context

A text file's read position is one row per `(source, path)` in `checkpoints`, holding the inode and a byte offset (`ingest/watcher.py`). The path is the key, so everything that changes what a path points to goes wrong in its own way. Proven by tests on #529:

| Case | What main does |
|---|---|
| Rename (`create`) on a single-file source | Lines written after the last pass and before the rename are lost |
| A rotated copy the source also lists | Read again from 0: its events are stored twice |
| `copytruncate`, refilled past the old offset before the next pass | The first lines of the new content are skipped |
| A new file that got a deleted file's inode number | Continues from the old file's offset |

#529 patched the path-keyed table (a start hash, moving rows between names, a scan for the renamed file). Three review rounds each found a new High case: the tail of a rotated file stored again on every pass while the new file is empty or unreadable; a new file with the same first bytes skipping its start; a rotation between listing and reading doubling a copy. The cause is the same each time: two files share one row, or one file has two.

## Decision

| # | Topic | Proposed default | Why | Alternative |
|---|---|---|---|---|
| 1 | Key | One position record per file: `(source, device, inode)` plus two content checks, a hash of the first 256 bytes and a hash of the 256 bytes before the offset. The path is a column that says where the file was last seen, never the key | A rename changes only the column. Two files can never share a record, and one file never has two | Keep the path key and add rules (what #529 tried) |
| 2 | Using a record | A file is opened first, then identified from the open handle (`fstat`, then both hashes). The record is used only when all match; otherwise the file is new and starts at 0 with its own record | The name is never trusted, so a rotation between listing and reading cannot mix two files. A reused inode number fails the hashes | Identify by name and inode before opening (the race in #529 round 3) |
| 3 | Following a rename | The watcher keeps the handle of each file it read from in the last 10 minutes (at most 256 handles, oldest closed first). When the name stops pointing at that file, it reads the held handle to its end, then keeps it 30 seconds more for a late write before closing | No folder scan and no guess about the new name: the handle is the file, wherever it moved, even if it is compressed or deleted meanwhile. The old file's record moves forward on its own, so an empty or unreadable new file cannot cause a repeat | Scan the folder for the old inode (limits, and wrong when the copy is compressed first) |
| 4 | After a restart | Handles are gone. Each listed file is matched to a record by row 2. A file renamed while the server was down is found only if the source lists it; otherwise its unread tail is not read, and the source page says so once | States the limit instead of guessing | Scan sibling files after every start (reads files the source does not cover unless every check is right) |
| 5 | Last line without a newline | When a held handle is closed (row 3), a remaining part line is stored as a line, `parse_status=partial` | The writer has moved on; dropping it loses data silently | Drop it |
| 6 | `copytruncate` | A file shorter than its offset, or whose hashes no longer match, starts again at 0 under a new record. A copy the source lists is a new file and is read from 0. The guide says to use `create` | The truncate cannot be seen reliably from outside, and logrotate itself loses lines between copy and truncate | Treat a listed file with the same content as an already read one as a copy and skip it (content match; needs its own tests, later) |
| 7 | Idle files | A file whose size, modified time and inode equal the record is not opened or hashed | #529 opened and hashed every file each pass: about 13% slower on 3,000 idle files | Hash every pass |
| 8 | Old records | Records of files not seen for 30 days are removed by the daily maintenance sweep | Today they stay for ever, which is what lets a reused inode number find one | Keep them |
| 9 | Files outside the source | Only files the source lists, or handles it already held, are ever read. No file is picked by inode number alone | #529 round 1: an unrelated file with a reused inode was stored under the source, with its classification and access scope | n/a |
| 10 | Update and rollback | New table `file_positions` (additive). At first start each `checkpoints` row is copied when its path still has the recorded inode; other rows are left. `checkpoints` keeps being written for text files, so a rollback reads on from it | Nothing is read twice at the update, and going back needs no step | Convert in place (no way back) |

Scope: text files only. EVTX, syslog spools, Loki, and connectors keep their own positions.

## What stays unsolved

- Lines written between copy and truncate under `copytruncate` (lost before Remnant can read them).
- A file renamed out of the source's pattern while the server is down (row 4).
- More than 256 files written to within 10 minutes in one process: the oldest handles are closed, and a rename of one of those is handled as row 4.
- A held handle keeps a deleted file's disk space until it is closed (at most 30 seconds after the rename is seen).

## Tests (written first)

The 10 tests of #529 plus one for each review finding: empty new file, unreadable new file, same first 256 bytes under a new name, three-file rotate chain, rotation between listing and reading, part line at close, more than 256 active files, restart between rename and read, copy listed by a folder source, 30-day sweep. An ingest pass timing case on 3,000 idle files, compared with main in the same run.

## Build plan (about 400 lines each)

1. `file_positions` table, identity from the open handle, the copy at update, idle-file skip; all cases that need no rename following.
2. Held handles: rename following, the part line, the handle limit.
3. The 30-day sweep, the source page note for row 4, SPEC 3.5 row, guide text.

## Questions for the owner

1. Accept row 3 (held file handles)? It is the part that makes rename handling exact; without it the design falls back to row 4 for every rename.
2. Row 5: store the part line as `partial`, or drop it?
3. Row 6: is "use `create`; a listed copy is read again" enough, or should the content match for copies be built too?
