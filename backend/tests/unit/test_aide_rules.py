"""AIDE rules from the update script (owner, 2026-11-01): the data folder's lake, rollup,
tmp, enrichment, and meta.sqlite, and frontend/node_modules, are skipped; tls/, .venv,
.python, backend/app, frontend/dist, and .git stay watched. The data folder comes from the
service's settings, so a custom one gets matching rules. Checked with AIDE itself when it
is installed, and with the same regular expressions otherwise."""

import gzip
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "update-systemd.sh"
KEPT = ["tls/server.key", "tls/server.crt", ".key"]
KEPT_INSTALL = [
    "backend/.venv/bin/python",
    ".python/cpython/bin/python3",
    "backend/app/main.py",
    "frontend/dist/index.html",
    ".git/hooks/post-merge",
]
SKIPPED = [
    "lake/source=a/day=2026-11-01/part-0.parquet",
    "rollup/m365/source=a/day=2026-10-31/part-0.parquet",
    "tmp/duckdb/duckdb_temp_storage.tmp",
    "enrichment/dbip-country.mmdb",
    "meta.sqlite",
    "meta.sqlite-wal",
]
SKIPPED_INSTALL = ["frontend/node_modules/react/index.js"]


def _rules(data: Path, install: Path, tmp: Path) -> str:
    env = tmp / "remnant.env"
    env.write_text(f'APP__SERVER__HOST=0.0.0.0\nAPP__PATHS__DATA_DIR="{data}/"\n')
    return subprocess.run(
        ["sh", str(SCRIPT), "--print-aide-rules"],
        env={"PATH": "/usr/bin:/bin", "ENV_FILE": str(env), "INSTALL_DIR": str(install)},
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


def _paths(data: Path, install: Path) -> tuple[list[str], list[str]]:
    kept = [f"{data}/{p}" for p in KEPT] + [f"{install}/{p}" for p in KEPT_INSTALL]
    skipped = [f"{data}/{p}" for p in SKIPPED] + [f"{install}/{p}" for p in SKIPPED_INSTALL]
    return kept, skipped


def test_default_layout_is_the_owner_rule_set(tmp_path: Path) -> None:
    text = _rules(Path("/var/lib/remnant"), Path("/opt/remnant"), tmp_path)
    assert [ln for ln in text.splitlines() if ln.startswith("!")] == [
        "!/var/lib/remnant/lake(/|$)",
        "!/var/lib/remnant/rollup(/|$)",
        "!/var/lib/remnant/tmp(/|$)",
        "!/var/lib/remnant/enrichment(/|$)",
        "!/var/lib/remnant/meta\\.sqlite",
        "!/opt/remnant/frontend/node_modules(/|$)",
    ]


@pytest.mark.parametrize("data", ["/var/lib/remnant", "/srv/remnant.data", "/data/r+1"])
def test_a_custom_data_folder_gets_matching_rules(tmp_path: Path, data: str) -> None:
    install = Path("/opt/remnant")
    text = _rules(Path(data), install, tmp_path)
    rules = [re.compile(ln[1:]) for ln in text.splitlines() if ln.startswith("!")]
    kept, skipped = _paths(Path(data), install)
    assert [p for p in kept if any(r.match(p) for r in rules)] == []
    assert [p for p in skipped if not any(r.match(p) for r in rules)] == []


@pytest.mark.skipif(shutil.which("aide") is None, reason="AIDE is not installed")
def test_rules_with_aide(tmp_path: Path) -> None:
    data, install = tmp_path / "var" / "lib" / "re.mnant", tmp_path / "opt" / "remnant"
    kept, skipped = _paths(data, install)
    for p in kept + skipped:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text("x")
    (tmp_path / "rules").write_text(_rules(data, install, tmp_path))
    conf = tmp_path / "aide.conf"
    conf.write_text(
        f"database_out=file:{tmp_path}/db.new\nFull = p+i+n+u+g+s+m+c+sha256\n"
        f"{tmp_path}/var Full\n{tmp_path}/opt Full\n@@include {tmp_path}/rules\n"
    )
    subprocess.run(["aide", "--init", "-c", str(conf)], capture_output=True, check=False)
    db = (tmp_path / "db.new").read_bytes()
    names = (gzip.decompress(db) if db[:2] == b"\x1f\x8b" else db).decode(errors="replace")
    for p in kept:
        assert f"{p} " in names, p
    for p in skipped:
        assert f"{p} " not in names, p
