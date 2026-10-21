"""Source discovery over a folder (SPEC 3.6, Slice 3). Suggestions only.

Walks a folder under the allowed roots, groups files into candidate sources by naming
pattern (a collector's per-host folders become one candidate listing its hosts), reads a
bounded sample of each, sniffs envelope and payload format, and ranks matching templates.
It reads files and nothing else: it creates no source, grants nothing, and changes no
classification. Every limit below exists because the folder may be large or hostile.
"""

import glob as globlib
import os
import re
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import SourceRejectedError
from app.ingest.evtx import EvtxReader
from app.ingest.sources import open_regular, resolve_source_path
from app.templates.matcher import Sniff, TemplateMatch, match_templates, sniff
from app.templates.tables import LookupTable
from app.templates.validator import Template

MAX_FILES = 5_000  # files kept per scan
MAX_ENTRIES = 50_000  # directory entries looked at per scan, kept or not
MAX_DEPTH = 4  # folder levels below the scanned folder
MAX_CANDIDATES = 200
SCAN_SECONDS = 60.0  # the whole scan stops (truncated) after this
SAMPLE_LINES = 200
SAMPLE_BYTES = 512 * 1024  # per candidate
SAMPLE_FILES = 3  # files sampled per candidate (different hosts when possible)
PREVIEW_LINES = 3
PREVIEW_CHARS = 300
_SKIP_SUFFIXES = (".gz", ".bz2", ".xz", ".zst", ".zip", ".7z", ".tar", ".tgz", ".lz4")
_DATE = re.compile(
    r"(?<!\d)(?:19|20)\d{2}[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])(?!\d)"
)
_ROTATION = re.compile(
    r"(?:\.\d{1,3}|[-.](?:19|20)\d{2}-?(?:0[1-9]|1[0-2])-?(?:0[1-9]|[12]\d|3[01])(?:\d{2,6})?)$"
)
_NUMBER_DIR = re.compile(r"\d{1,8}")  # 2026, 10, 01: date folders, not hosts
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass
class Candidate:
    path: str  # folder to give the new source
    glob: str  # file pattern relative to `path`
    files: list[Path] = field(default_factory=list)  # as listed (a link stays a link)
    real: list[Path] = field(default_factory=list)  # resolved, for reading
    hosts: set[str] = field(default_factory=set)
    size: int = 0


@dataclass(frozen=True, slots=True)
class CandidateReport:
    path: str
    glob: str
    files: int
    bytes: int
    hosts: list[str]
    kind: str  # text, evtx, or binary
    sniff: Sniff | None
    matches: list[TemplateMatch]
    preview: list[str]
    # Files the glob would pick up beyond this candidate's own (rotations, compressed
    # files, other candidates): the admin should narrow it before adding the source.
    extra_matches: int


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    root: str
    candidates: list[CandidateReport]
    skipped: dict[str, int]  # reason -> file count
    truncated: bool  # stopped at a file, entry, candidate, or time limit


def _pattern(name: str) -> str:
    """fw01-2026-10-09.log -> fw01-*.log (one file per day). Glob characters in a real
    file name are escaped, so the pattern never matches more than intended."""
    return _DATE.sub("*", globlib.escape(name))


def _dir_glob(part: str) -> str:
    return "*" if _NUMBER_DIR.fullmatch(part) or _DATE.fullmatch(part) else globlib.escape(part)


def _rotations(names: list[str]) -> set[str]:
    """auth.log.1, auth.log-20261008: rotated copies of a live auth.log in the same folder.
    The watcher follows the live file across rotation, so copies would be read twice."""
    live = set(names)
    out = set()
    for name in names:
        m = _ROTATION.search(name)
        if m and m.start() > 0 and name[: m.start()] in live:
            out.add(name)
    return out


def _decodable(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _walk(
    root: Path, allowed_roots: list[Path], skipped: Counter[str], deadline: float
) -> tuple[list[tuple[Path, Path]], bool]:
    """(listed path, resolved path) for every regular file to consider."""
    found: list[tuple[Path, Path]] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        depth = len(Path(dirpath).relative_to(root).parts)
        hidden = [d for d in dirnames if d.startswith(".")]
        # Names that are not valid UTF-8 cannot be shown, stored, or matched by a glob the
        # admin could type; they are counted and left out.
        undecodable = [d for d in dirnames if not d.startswith(".") and not _decodable(d)]
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in undecodable)
        if hidden:
            skipped["hidden"] += len(hidden)
        if undecodable:
            skipped["undecodable_name"] += len(undecodable)
        if depth >= MAX_DEPTH:
            skipped["too_deep"] += len(dirnames)
            dirnames[:] = []
        seen += len(dirnames) + len(filenames)
        if seen > MAX_ENTRIES or time.monotonic() > deadline:
            return found, True
        rotated = _rotations(filenames)
        for name in sorted(filenames):
            if name.startswith("."):  # editor swap files, .nfs* and the like
                skipped["hidden"] += 1
                continue
            if not _decodable(name):
                skipped["undecodable_name"] += 1
                continue
            if name.lower().endswith(_SKIP_SUFFIXES):
                skipped["compressed"] += 1
                continue
            if name in rotated:
                skipped["rotated"] += 1
                continue
            listed = Path(dirpath) / name
            try:
                real = resolve_source_path(listed, allowed_roots)
            except SourceRejectedError:
                skipped["outside_allowed_roots"] += 1
                continue
            if not real.is_file():
                skipped["not_a_file"] += 1
                continue
            found.append((listed, real))
            if len(found) >= MAX_FILES:
                return found, True
    return found, False


def _group(root: Path, files: list[tuple[Path, Path]]) -> dict[str, Candidate]:
    groups: dict[str, Candidate] = {}
    for listed, real in files:
        parts = listed.relative_to(root).parts
        dirs = parts[:-1]
        dirs_glob = [_dir_glob(d) for d in dirs]
        # The host is the deepest folder above the file that is not a date folder:
        # <host>/x.log, <category>/<host>/x.log, 2026/10/01/<host>/x.log, and
        # <host>/2026-10-01/x.log. Folders above it stay literal.
        named = [i for i, g in enumerate(dirs_glob) if g != "*"]
        host = ""
        if named:
            host = dirs[named[-1]]
            dirs_glob[named[-1]] = "*"
        glob = "/".join([*dirs_glob, _pattern(parts[-1])])
        cand = groups.setdefault(glob, Candidate(path=str(root), glob=glob))
        cand.files.append(listed)
        cand.real.append(real)
        if host:
            cand.hosts.add(host[:255])
        try:
            cand.size += real.stat().st_size
        except OSError:
            pass
    return groups


def _extra_matches(root: Path, cand: Candidate, allowed_roots: list[Path], deadline: float) -> int:
    """Files the suggested glob matches, as the watcher would read them (regular files
    inside the allowed roots), beyond the candidate's own. Zero means the source reads
    exactly what discovery grouped. Hidden files count: the glob reaches them."""
    own = set(cand.files)
    extra = 0
    for n, p in enumerate(root.glob(cand.glob)):
        if n % 1_000 == 0 and time.monotonic() > deadline:
            break
        if p in own:
            continue
        try:
            if resolve_source_path(p, allowed_roots).is_file():
                extra += 1
        except SourceRejectedError:
            continue
        if extra >= 1_000:
            break
    return extra


def is_evtx(path: Path, allowed_roots: list[Path]) -> bool:
    try:
        with open_regular(path, allowed_roots) as fh:
            return fh.read(8) == b"ElfFile\x00"
    except OSError:
        return False


def sample_text_files(files: list[Path], allowed_roots: list[Path]) -> tuple[list[str], bool]:
    lines: list[str] = []
    budget = SAMPLE_BYTES
    per_file = max(SAMPLE_LINES // max(len(files), 1), 1)
    binary = False
    for f in files:
        try:
            with open_regular(f, allowed_roots) as fh:
                data = fh.read(min(budget, SAMPLE_BYTES // max(len(files), 1)))
        except OSError:
            continue
        budget -= len(data)
        if data.count(b"\x00") > len(data) // 100:
            binary = True
            continue
        cut = data.rfind(b"\n")
        if cut >= 0 and len(data) == SAMPLE_BYTES // max(len(files), 1):
            data = data[: cut + 1]  # drop a partial last line
        text = data.decode("utf-8", errors="replace").splitlines()
        lines.extend(line for line in text[:per_file] if line.strip())
    return lines[:SAMPLE_LINES], binary and not lines


def sample_evtx_files(files: list[Path], allowed_roots: list[Path]) -> list[str]:
    reader = EvtxReader(max_records=SAMPLE_LINES // max(len(files), 1), max_chunks=2)
    lines: list[str] = []
    for f in files:
        try:
            with open_regular(f, allowed_roots) as fh:
                batch = reader.read(fh, 0)
        except OSError:
            continue
        lines.extend(frame.data.decode("utf-8", errors="replace") for _, frame in batch.frames)
    return lines[:SAMPLE_LINES]


def _spread(cand: Candidate) -> list[Path]:
    """Up to SAMPLE_FILES resolved files, from different folders (hosts) when possible."""
    by_parent: dict[Path, Path] = {}
    for listed, real in sorted(zip(cand.files, cand.real, strict=True)):
        by_parent.setdefault(listed.parent, real)
    return list(by_parent.values())[:SAMPLE_FILES]


def _preview(lines: list[str]) -> list[str]:
    return [_CONTROL.sub("?", line)[:PREVIEW_CHARS] for line in lines[:PREVIEW_LINES]]


def discover(
    folder: str,
    allowed_roots: list[Path],
    templates: Iterable[Template],
    tables: Mapping[str, LookupTable] | None = None,
) -> DiscoveryReport:
    root = resolve_source_path(folder, allowed_roots)
    if not root.is_dir():
        raise SourceRejectedError("Discovery needs a folder, not a file")
    deadline = time.monotonic() + SCAN_SECONDS
    skipped: Counter[str] = Counter()
    files, truncated = _walk(root, allowed_roots, skipped, deadline)
    groups = _group(root, files)
    if len(groups) > MAX_CANDIDATES:
        truncated = True
    template_list = list(templates)
    reports: list[CandidateReport] = []
    for key in sorted(groups)[:MAX_CANDIDATES]:
        if time.monotonic() > deadline:
            truncated = True
            break
        cand = groups[key]
        picked = _spread(cand)
        if all(is_evtx(f, allowed_roots) for f in picked):
            kind, lines = "evtx", sample_evtx_files(picked, allowed_roots)
            framing = "evtx"
        else:
            lines, binary = sample_text_files(picked, allowed_roots)
            kind, framing = ("binary" if binary else "text"), "lines"
        reports.append(
            CandidateReport(
                path=cand.path,
                glob=cand.glob,
                files=len(cand.files),
                bytes=cand.size,
                hosts=sorted(cand.hosts)[:100],
                kind=kind,
                sniff=sniff(lines) if lines and kind == "text" else None,
                matches=match_templates(lines, template_list, tables, framing=framing),
                preview=_preview(lines),
                extra_matches=_extra_matches(root, cand, allowed_roots, deadline),
            )
        )
    return DiscoveryReport(str(root), reports, dict(skipped), truncated)
