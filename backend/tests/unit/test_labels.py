"""Loki stream labels stand in for a stripped syslog header (install finding 10)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ingest.envelope import EnvelopeParser
from app.ingest.labels import labels_envelope
from app.ingest.normalizer import SourceSpec
from app.ingest.records import DecodedLine
from app.templates.registry import STARTER_DIR, TemplateRegistry
from app.templates.router import AutoNormalizer

STREAMS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "loki" / "streams.json").read_text(encoding="utf-8")
)
REGISTRY = TemplateRegistry(STARTER_DIR, Path("/nonexistent"))
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def _auto() -> AutoNormalizer:
    return AutoNormalizer(
        SourceSpec(source_id="loki", format="syslog"),
        REGISTRY.all(),
        REGISTRY.starter_ids,
        clock=lambda: NOW,
        tables=REGISTRY.tables,
    )


@pytest.mark.parametrize("stream", STREAMS, ids=lambda s: s["line"][:40])
def test_stream_labels_route_and_fill_the_envelope(stream: dict[str, Any]) -> None:
    hint = labels_envelope(stream["labels"])
    line = DecodedLine(text=stream["line"], bytes_invalid=False, truncated=False, hint=hint)
    row = _auto().normalize(line)
    assert row is not None
    assert row["raw"] == stream["line"]  # the line is never changed
    for key, want in stream["expect"].items():
        assert row[key] == want, key


def test_no_host_is_invented_from_message_text() -> None:
    """A line with a date and a bracketed word is not a header: no '[INFO]' host."""
    stream = next(s for s in STREAMS if "[INFO]" in s["line"])
    line = DecodedLine(stream["line"], False, False, labels_envelope(stream["labels"]))
    row = _auto().normalize(line)
    assert row is not None and row["device_hostname"] == "app02"
    assert json.loads(row["envelope"])["rfc"] == "labels"


def test_a_real_header_in_the_line_wins_over_labels() -> None:
    hint = labels_envelope({"hostname": "relay01", "app_name": "rsyslogd"})
    env = EnvelopeParser().parse("<38>Oct 12 11:20:00 bastion sshd[7]: hello", hint)
    assert (env.rfc, env.hostname, env.app_name) == ("3164", "bastion", "sshd")


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ({"host": "h1", "program": "cron", "pid": "5"}, ("h1", "cron", "5", None)),
        (
            {"hostname": "h1", "app_name": "x", "severity": "err", "facility": "auth"},
            ("h1", "x", None, 35),
        ),
        (
            {"hostname": "h1", "app_name": "x", "level": "warning"},
            ("h1", "x", None, 12),
        ),  # user facility
        ({"hostname": "h1", "app_name": "x", "severity": "loud"}, ("h1", "x", None, None)),
        ({"hostname": "h1", "app_name": "-", "proc_id": ""}, ("h1", None, None, None)),
    ],
)
def test_label_map_defaults(labels: dict[str, str], expected: tuple[Any, ...]) -> None:
    env = labels_envelope(labels)
    assert env is not None
    assert (env.hostname, env.app_name, env.procid, env.pri) == expected


def test_no_envelope_without_host_or_program() -> None:
    assert labels_envelope({"job": "syslog", "severity": "info"}) is None


def test_label_map_overrides_per_source() -> None:
    env = labels_envelope({"node": "n1", "svc": "api"}, {"hostname": ["node"], "app_name": ["svc"]})
    assert env is not None and (env.hostname, env.app_name) == ("n1", "api")
    off = labels_envelope({"hostname": "h1", "app_name": "x"}, {"app_name": []})
    assert off is not None and off.app_name is None
