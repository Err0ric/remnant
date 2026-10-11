"""Automatic parser (ADR-0012): each line of a mixed stream goes to one template, or generic."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ingest.normalizer import SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.sources import SourceConfig
from app.templates.registry import STARTER_DIR, TemplateRegistry
from app.templates.router import AutoNormalizer
from app.templates.validator import Template

MIXED = Path(__file__).parents[1] / "fixtures" / "mixed"
REGISTRY = TemplateRegistry(STARTER_DIR, Path("/nonexistent"))
NOW = datetime(2026, 10, 10, tzinfo=UTC)


def _auto(templates: list[Template] | None = None, starter: frozenset[str] | None = None):
    return AutoNormalizer(
        SourceSpec(source_id="mixed", format="syslog"),
        REGISTRY.all() if templates is None else templates,
        REGISTRY.starter_ids if starter is None else starter,
        clock=lambda: NOW,
        tables=REGISTRY.tables,
    )


def _line(text: str) -> DecodedLine:
    return DecodedLine(text=text, bytes_invalid=False, truncated=False)


def test_mixed_stream_routes_every_line_to_the_expected_parser() -> None:
    lines = (MIXED / "sample.log").read_text(encoding="utf-8").splitlines()
    expected = (MIXED / "expected_templates.txt").read_text(encoding="utf-8").splitlines()
    auto = _auto()
    rows = [auto.normalize(_line(text)) for text in lines]
    assert [r["template_id"] for r in rows if r] == expected
    for text, row in zip(lines, rows, strict=True):
        assert row is not None
        assert row["raw"] == text  # rule 5
    routed = [r for r in rows if r and not r["template_id"].startswith("generic_")]
    assert all(r["parse_status"] in ("ok", "partial") for r in routed)


def test_routed_lines_fill_the_columns_the_generic_parser_leaves_empty() -> None:
    sshd = "<38>Oct  9 20:02:25 db-01 sshd[13445]: Accepted publickey for deploy from 10.20.2.14 port 53708 ssh2"
    row = _auto().normalize(_line(sshd))
    assert row is not None
    assert (row["template_id"], row["actor_user_name"], row["src_endpoint_ip"]) == (
        "linux_sshd",
        "deploy",
        "10.20.2.14",
    )


def test_a_template_that_fails_on_its_line_falls_back_to_generic() -> None:
    cron = "<78>Oct  9 20:03:01 web-01 CRON[4411]: (root) CMD (/usr/local/bin/backup.sh)"
    auto = _auto()
    assert auto.route(cron) is not None and auto.route(cron).id == "linux_pam"  # type: ignore[union-attr]  # checked in the same expression
    row = auto.normalize(_line(cron))
    assert row is not None
    assert row["template_id"] == "generic_syslog"
    assert row["parse_errors"].startswith("auto_fallback:linux_pam")
    assert row["device_hostname"] == "web-01" and row["time"] is not None


def test_user_templates_are_tried_before_starter_ones_and_catch_alls_last() -> None:
    cef = REGISTRY.get("cef_generic")
    assert cef is not None
    mine = cef.model_copy(update={"id": "acme_cef", "vendor": ""})
    auto = _auto([*REGISTRY.all(), mine])
    line = "<132>Oct  9 20:00:31 fw01 CEF:0|Acme|Proxy|7.1|sig-1|Policy allowed|3|src=198.51.100.4"
    picked = auto.route(line)
    assert picked is not None and picked.id == "acme_cef"
    # Without the user copy, the starter catch-all still takes it after vendor templates.
    picked = _auto().route(line)
    assert picked is not None and picked.id == "cef_generic"


def test_multiline_templates_are_never_routed_to() -> None:
    sshd = REGISTRY.get("linux_sshd")
    assert sshd is not None
    multi = sshd.model_copy(
        update={
            "id": "aaa_multi",
            "framing": sshd.framing.model_copy(
                update={"multiline": sshd.framing.multiline.model_copy(update={"start": "^<"})}
            ),
        }
    )
    picked = _auto([multi, sshd]).route("<38>Oct  9 20:02:25 db-01 sshd[1]: Accepted x")
    assert picked is not None and picked.id == "linux_sshd"


def test_a_hostile_line_is_bounded_and_still_stored() -> None:
    garbage = "<13>Oct  9 20:03:05 h app: " + ("a" * 10_000) + "!"
    row = _auto().normalize(_line(garbage))
    assert row is not None and row["raw"] == garbage


def test_auto_is_a_reserved_id_and_not_for_csv() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        Template.model_validate(
            {**REGISTRY.get("linux_sshd").model_dump(by_alias=True), "id": "auto"}  # type: ignore[union-attr]  # starter template exists
        )
    with pytest.raises(ValidationError, match="not CSV"):
        SourceConfig(source_id="x", format="csv", path="/x", template_id="auto")
    assert SourceConfig(source_id="x", format="syslog", path="/x", template_id="auto")


def test_match_block_takes_a_dominant_tag_only() -> None:
    from app.templates.matcher import match_block

    sshd = ["<38>Oct  9 20:02:25 h sshd[1]: Accepted x"] * 9 + ["<38>Oct  9 20:02:25 h cron[1]: y"]
    assert match_block(sshd) == {"app_name": ["sshd"], "min_confidence": 0.8}
    mixed = sshd[:5] + ["<38>Oct  9 20:02:25 h sudo[1]: z"] * 5
    assert match_block(mixed) == {"min_confidence": 0.8}
    assert match_block(["no header here"] * 3) == {"min_confidence": 0.8}
    assert match_block([]) == {"min_confidence": 0.8}
