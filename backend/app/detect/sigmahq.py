"""The SigmaHQ core rule package: one pinned release, or the same zip uploaded (D211).

The one exception to "none fetched" (D32): on an admin's click, the server downloads the
pinned asset below from github.com and checks its SHA-256 before reading a byte of it. A
mismatch imports nothing. Nothing here runs on start-up or on a schedule. Offline
installs upload the zip instead (any SigmaHQ package, checked by the same reader).

The archive is untrusted input. It is never extracted to disk: members are read in
memory, only `*.yml` / `*.yaml`, with a cap per member, on the total, and on the number of
members, so a zip bomb stops at the caps and a member named `../../etc/x.yml` is only ever
a label (and is skipped anyway).
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

from app.alerts.net import egress
from app.core.errors import RuleRejectedError

# The pinned release: SigmaHQ/sigma `r2026-07-01`, asset `sigma_core.zip` (1,399,726 bytes).
# Updating it is a code change: new tag, new hash, checked by hand against the release.
RELEASE_TAG = "r2026-07-01"
ASSET_NAME = "sigma_core.zip"
ASSET_SHA256 = "45ccbd62cbf0d7ccca6f44eaa010f86bb24f082b5411c5e22c71907e7770ee46"
ASSET_URL = f"https://github.com/SigmaHQ/sigma/releases/download/{RELEASE_TAG}/{ASSET_NAME}"
# github.com answers with a redirect to its release asset storage.
ALLOWED_HOSTS = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)
MAX_REDIRECTS = 3
TIMEOUT_S = 60.0

MAX_ZIP_BYTES = 20 * 1024 * 1024  # the core package is about 1.4 MB
MAX_MEMBERS = 10_000
MAX_MEMBER_BYTES = 512 * 1024  # as rules.MAX_RULE_BYTES
MAX_TOTAL_BYTES = 200 * 1024 * 1024  # uncompressed, as a folder import
_SUFFIXES = (".yml", ".yaml")

ClientFactory = Callable[[], httpx.Client]


def default_client() -> httpx.Client:
    out = egress()
    return httpx.Client(
        timeout=TIMEOUT_S,
        verify=out.verify(),
        proxy=out.proxy(),
        follow_redirects=False,  # followed by hand, only to ALLOWED_HOSTS
        # identity: the SHA-256 is of the asset's exact bytes, never a re-encoded body
        headers={"User-Agent": "sigma-rule-import", "Accept-Encoding": "identity"},
    )


def fetch_pinned(client: ClientFactory | None = None) -> bytes:
    """The pinned asset's bytes, only if their SHA-256 is the pinned one."""
    url = ASSET_URL
    factory = client or default_client  # looked up per call, so tests can swap it
    try:
        with factory() as http:
            for _ in range(MAX_REDIRECTS + 1):
                parts = urlsplit(url)
                if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
                    raise RuleRejectedError(
                        "The download was sent outside GitHub; nothing imported"
                    )
                with http.stream("GET", url) as res:
                    if res.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, res.headers.get("location", ""))
                        continue
                    if res.status_code != 200:
                        raise RuleRejectedError(
                            f"GitHub answered HTTP {res.status_code}; nothing imported"
                        )
                    data = _capped(res)
                    break
            else:
                raise RuleRejectedError("Too many redirects from GitHub; nothing imported")
    except httpx.TimeoutException as exc:
        raise RuleRejectedError("GitHub did not answer in time; nothing imported") from exc
    except httpx.HTTPError as exc:
        raise RuleRejectedError(
            "Could not reach GitHub (check the network or proxy settings); nothing imported"
        ) from exc
    if hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise RuleRejectedError(
            f"The downloaded {ASSET_NAME} does not match the pinned SHA-256 for {RELEASE_TAG};"
            " nothing imported"
        )
    return data


def _capped(res: httpx.Response) -> bytes:
    declared = res.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_ZIP_BYTES:
        raise RuleRejectedError("The download is larger than 20 MB; nothing imported")
    out = bytearray()
    for chunk in res.iter_bytes():  # decoded as it streams, so the cap also bounds gzip
        out += chunk
        if len(out) > MAX_ZIP_BYTES:
            raise RuleRejectedError("The download is larger than 20 MB; nothing imported")
    return bytes(out)


@dataclass(frozen=True, slots=True)
class Member:
    name: str  # as shown and stored; never used as a path
    data: bytes | None  # None when skipped
    reason: str = ""  # why it was skipped


@dataclass(slots=True)
class Walk:
    truncated: bool = False


def safe_name(name: str) -> bool:
    """A relative POSIX name with no `..`, drive, backslash, or control characters."""
    if not name or "\\" in name or any(ord(c) < 32 for c in name) or ":" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def members(data: bytes, walk: Walk) -> Iterator[Member]:
    """The archive's rule files, read in memory under the caps. Not-rule members (the
    license text, folders) are passed over silently."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise RuleRejectedError("The file is not a zip archive; nothing imported") from exc
    total = 0
    count = 0
    with archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(_SUFFIXES):
                continue
            count += 1
            if count > MAX_MEMBERS:
                walk.truncated = True
                return
            name = info.filename[:500]
            if not safe_name(info.filename):
                yield Member(name, None, "Unsafe file name in the archive")
                continue
            if info.flag_bits & 0x1:
                yield Member(name, None, "Encrypted member")
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                yield Member(name, None, f"Rule file is larger than {MAX_MEMBER_BYTES // 1024} KB")
                continue
            try:
                with archive.open(info) as fh:
                    body = fh.read(MAX_MEMBER_BYTES + 1)  # the header's size may lie
            except (zipfile.BadZipFile, OSError, NotImplementedError, EOFError):
                yield Member(name, None, "Member could not be read")
                continue
            if len(body) > MAX_MEMBER_BYTES:
                yield Member(name, None, f"Rule file is larger than {MAX_MEMBER_BYTES // 1024} KB")
                continue
            total += len(body)
            if total > MAX_TOTAL_BYTES:
                walk.truncated = True
                return
            yield Member(name, body)
