"""Backup and restore of the data folder (app-admin backup / verify-backup / restore)."""

import hashlib
import io
import json
import sqlite3
import stat
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import admin
from app.auth.users import UserStore
from app.ingest.framer import Framer
from app.ingest.lakelock import lake_lock
from app.ingest.maintenance import LakeMaintenance
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox
from app.ops import backup as ops

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
LOG = b"<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for jordan\n"


def make_data(root: Path) -> Path:
    data = root / "data"
    UserStore(MetaDB(data / "meta.sqlite")).create("admin", "correct horse battery", "admin")
    n = Normalizer(SourceSpec(source_id="linux_auth", format="syslog"), clock=lambda: NOW)
    LakeWriter(data / "lake").write(
        [r for f in Framer().frames([LOG]) if (r := n.normalize(decode_frame(f)))]
    )
    (data / "templates").mkdir()
    (data / "templates" / "mine.yaml").write_text("id: mine\n")
    (data / "lake" / "source=linux_auth" / "day=2026-10-09" / ".part-x.parquet.tmp").write_bytes(
        b"half written"
    )
    SecretBox(data).encrypt("provider-key")  # creates .key
    return data


def snapshot(data: Path) -> dict[str, str]:
    files = {}
    for p in sorted(data.rglob("*")):
        rel = p.relative_to(data).as_posix()
        if p.is_file() and not rel.endswith((".tmp", ".lock")) and rel != "meta.sqlite":
            files[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return files


def take(data: Path, archive: Path, include_key: bool = True) -> ops.BackupInfo:
    with archive.open("wb") as fh:
        return ops.create(data, fh, include_key=include_key)


def test_round_trip(tmp_path: Path) -> None:
    data = make_data(tmp_path)
    archive = tmp_path / "b.tar.gz"
    info = take(data, archive)
    assert info.has_key and info.schema_version == len(ops.MIGRATIONS)
    names = tarfile.open(archive).getnames()
    assert names[0] == "manifest.json" and ".key" in names
    assert not any(n.endswith((".tmp", ".lock")) for n in names)

    target = tmp_path / "restored"
    restored, kept = ops.restore(archive, target)
    assert kept is None and restored.files == info.files
    assert snapshot(target) == snapshot(data)
    users = sqlite3.connect(target / "meta.sqlite").execute("SELECT username FROM users")
    assert [r[0] for r in users] == ["admin"]
    assert SecretBox(target).decrypt(SecretBox(data).encrypt("x")) == "x"  # same key
    assert stat.S_IMODE((target / ".key").stat().st_mode) == 0o600


def test_without_key(tmp_path: Path) -> None:
    data = make_data(tmp_path)
    info = take(data, tmp_path / "b.tar.gz", include_key=False)
    assert not info.has_key
    assert ".key" not in tarfile.open(tmp_path / "b.tar.gz").getnames()


def _rewrite(archive: Path, change: dict[str, bytes], manifest_edit: object = None) -> Path:
    """Copy an archive with some members' bytes replaced (or added), manifest unchanged."""
    out = archive.with_name("edited.tar.gz")
    with tarfile.open(archive) as src, tarfile.open(out, "w:gz") as dst:
        for m in src.getmembers():
            body = src.extractfile(m).read()  # type: ignore[union-attr]  # regular files only
            if m.name == "manifest.json" and callable(manifest_edit):
                body = json.dumps(manifest_edit(json.loads(body))).encode()
            body = change.pop(m.name, body)
            info = tarfile.TarInfo(m.name)
            info.size = len(body)
            dst.addfile(info, io.BytesIO(body))
        for name, body in change.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            dst.addfile(info, io.BytesIO(body))
    return out


def test_damaged_backup_is_refused_and_nothing_written(tmp_path: Path) -> None:
    data = make_data(tmp_path)
    archive = tmp_path / "b.tar.gz"
    take(data, archive)
    damaged = _rewrite(archive, {"templates/mine.yaml": b"id: evil\n"})
    with pytest.raises(ops.BackupError, match="Checksum mismatch"):
        ops.verify(damaged)
    target = tmp_path / "restored"
    with pytest.raises(ops.BackupError):
        ops.restore(damaged, target)
    assert not target.exists() or not any(target.iterdir())


@pytest.mark.parametrize("name", ["../escape", "/etc/passwd", "lake/../../x", "notes.txt"])
def test_unsafe_names_refused(tmp_path: Path, name: str) -> None:
    data = make_data(tmp_path)
    archive = tmp_path / "b.tar.gz"
    take(data, archive)

    def add(manifest: dict[str, object]) -> dict[str, object]:
        manifest["files"].append({"path": name, "sha256": "0", "bytes": 1})  # type: ignore[attr-defined]  # test data
        return manifest

    with pytest.raises(ops.BackupError, match="unsafe"):
        ops.verify(_rewrite(archive, {name: b"x"}, add))


def test_existing_data_needs_replace_and_is_kept(tmp_path: Path) -> None:
    data = make_data(tmp_path)
    archive = tmp_path / "b.tar.gz"
    take(data, archive)
    other = make_data(tmp_path / "other")
    (other / "templates" / "newer.yaml").write_text("id: newer\n")
    with pytest.raises(ops.BackupError, match="--replace"):
        ops.restore(archive, other)
    _, kept = ops.restore(archive, other, replace=True)
    assert kept is not None and (kept / "templates" / "newer.yaml").is_file()
    assert not (other / "templates" / "newer.yaml").exists()
    restored = {k: v for k, v in snapshot(other).items() if not k.startswith(".before-restore-")}
    assert restored == snapshot(data)


def test_backup_from_newer_version_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = make_data(tmp_path)
    archive = tmp_path / "b.tar.gz"
    take(data, archive)
    monkeypatch.setattr(ops, "MIGRATIONS", ops.MIGRATIONS[:5])
    with pytest.raises(ops.BackupError, match="newer version"):
        ops.restore(archive, tmp_path / "restored")


def test_maintenance_waits_while_a_backup_holds_the_lake(tmp_path: Path) -> None:
    calls: list[str] = []

    class Sources:
        def list(self) -> list[object]:
            return []

    m = LakeMaintenance(tmp_path / "lake", Sources(), 30, 0, 0)  # type: ignore[arg-type]  # stub
    m.compact = lambda: calls.append("compact")  # type: ignore[method-assign,assignment,return-value]  # spy
    with lake_lock(tmp_path / "lake"):
        m.tick()
    assert calls == []
    m.tick()
    assert calls == ["compact"]


def test_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = make_data(tmp_path)
    monkeypatch.setenv("APP__PATHS__DATA_DIR", str(data))
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(admin.app, ["backup", "-o", "nightly.tar.gz"])
    assert res.exit_code == 0, res.output
    assert stat.S_IMODE((tmp_path / "nightly.tar.gz").stat().st_mode) == 0o600
    again = runner.invoke(admin.app, ["backup", "-o", "nightly.tar.gz"])
    assert again.exit_code == 1  # never overwrites an existing file
    res = runner.invoke(admin.app, ["verify-backup", "nightly.tar.gz"])
    assert res.exit_code == 0 and "Backup OK" in res.output
    monkeypatch.setenv("APP__PATHS__DATA_DIR", str(tmp_path / "fresh"))
    res = runner.invoke(admin.app, ["restore", "nightly.tar.gz"])
    assert res.exit_code == 0, res.output
    assert snapshot(tmp_path / "fresh") == snapshot(data)
