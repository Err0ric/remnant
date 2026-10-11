# ruff: noqa: F811  # `lab` is the shared pytest fixture, used by name as a parameter
"""Redaction in the gate (ADR-0010, D36): opt-in, cloud only, ask/explain/report only."""

import json

import pytest

from app.core.errors import ProviderConfigError
from app.llm.gate import data_message
from app.llm.provider import ProviderResponse
from app.llm.redact import Redactor, derive_key
from tests.unit.test_llm_gate import (  # noqa: F401  # lab is a pytest fixture
    CLOUD_URL,
    LOCAL_URL,
    Answer,
    Lab,
    calls,
    lab,
    provider,
    request,
)

KEY = b"k" * 32
EVENT = {"src_endpoint_ip": "203.0.113.9", "raw": "Failed password from 203.0.113.9"}


def sent_text(lab: Lab) -> str:
    return json.dumps([m.content for m in lab.fakes[-1].seen[-1]["messages"]])


def opt_in(lab: Lab, url: str, name: str = "p") -> str:
    pid = provider(lab, url, name)
    lab.store.update(pid, None, None, None, None, None, False, redact=True)
    lab.gate._redaction_key = lambda: KEY
    return pid


def test_redaction_is_off_unless_the_provider_opts_in(lab: Lab) -> None:
    pid = provider(lab, CLOUD_URL)
    lab.gate._redaction_key = lambda: KEY
    lab.gate.call(request(lab, pid, ["fw_edge"], messages=[data_message(EVENT, ["fw_edge"])]))
    assert "203.0.113.9" in sent_text(lab)
    assert calls(lab)[-1]["redaction_applied"] == 0


def test_opted_in_cloud_calls_send_tokens_and_callers_get_real_values(lab: Lab) -> None:
    pid = opt_in(lab, CLOUD_URL)
    token = Redactor(derive_key(KEY)).token("IP", "203.0.113.9")
    lab.reply[0] = ProviderResponse(
        text=json.dumps({"sql": f"SELECT * FROM events WHERE src_endpoint_ip = '{token}'"}),
        model="m",
    )
    result = lab.gate.call(
        request(
            lab,
            pid,
            ["fw_edge"],
            messages=[data_message(EVENT, ["fw_edge"])],
            response_model=Answer,
        )
    )
    assert "203.0.113.9" not in sent_text(lab) and token in sent_text(lab)
    assert isinstance(result.parsed, Answer) and "'203.0.113.9'" in result.parsed.sql
    row = calls(lab)[-1]
    assert row["redaction_applied"] == 1 and json.loads(row["redaction_counts"]) == {"IP": 1}


def test_local_providers_and_parser_drafts_are_never_redacted(lab: Lab) -> None:
    local = opt_in(lab, LOCAL_URL)
    lab.gate.call(request(lab, local, ["fw_edge"], messages=[data_message(EVENT, ["fw_edge"])]))
    assert "203.0.113.9" in sent_text(lab)
    cloud = opt_in(lab, CLOUD_URL, "cloud")
    lab.gate.call(
        request(
            lab,
            cloud,
            [],
            purpose="parser_draft",
            messages=[data_message(EVENT, ["fw_edge"])],
        )
    )
    assert "203.0.113.9" in sent_text(lab)


def test_no_key_means_no_call(lab: Lab) -> None:
    pid = opt_in(lab, CLOUD_URL)
    lab.gate._redaction_key = None
    with pytest.raises(ProviderConfigError, match="Redaction"):
        lab.gate.call(request(lab, pid, ["fw_edge"], messages=[data_message(EVENT, ["fw_edge"])]))
    assert not lab.fakes or all(f.seen == [] for f in lab.fakes)
