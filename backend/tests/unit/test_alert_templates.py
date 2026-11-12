"""ADR-0049 3.1: an `emits: alerts` template, its required fields, and the key it stores."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.ingest.records import DecodedLine
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer
from app.templates.validator import Template

STARTER = Path(__file__).resolve().parents[3] / "templates" / "starter"
ALERT = (
    "<132>Nov  9 20:41:12 sensor01 CEF:0|ExampleCorp|EdgeSensor|2.1|sig-9|Credential"
    " dumping detected|9|externalId=A-1001 src=10.20.1.5 suser=alice shost=ws-0042"
)


def cef_alert(**change: Any) -> dict[str, Any]:
    """The generic CEF starter template made an alert source."""
    doc: dict[str, Any] = yaml.safe_load((STARTER / "cef_generic.yaml").read_text())
    doc["id"] = "cef_alerts_test"
    doc["mapping"]["class_uid"] = 2004
    doc["mapping"]["fields"]["src_endpoint_hostname"] = {"from": "shost"}
    doc["emits"] = "alerts"
    doc["alert"] = {"id": "externalId", "product": ["device_vendor", "device_product"]}
    doc.update(change)
    return doc


def template(**change: Any) -> Template:
    return parse_template(yaml.safe_dump(cef_alert(**change)))


def normalize(t: Template, text: str) -> dict[str, Any]:
    line = DecodedLine(text=text, bytes_invalid=False, truncated=False)
    return TemplateNormalizer(t, "edr").normalize(line)


def test_emits_alerts_needs_a_key_and_detection_finding() -> None:
    with pytest.raises(ValidationError, match=r"alert\.id and alert\.product"):
        Template.model_validate(cef_alert(alert=None))
    doc = cef_alert()
    doc["mapping"]["class_uid"] = 0
    with pytest.raises(ValidationError, match="class_uid 2004"):
        Template.model_validate(doc)
    with pytest.raises(ValidationError, match="only for a template with emits"):
        Template.model_validate(cef_alert(emits=""))


def test_a_complete_alert_stores_its_key() -> None:
    row = normalize(template(), ALERT)
    assert row["parse_status"] == "ok", row["parse_errors"]
    assert row["raw"] == ALERT
    key = json.loads(row["unmapped"])["_alert"]
    assert key == {"id": "A-1001", "product": "ExampleCorp EdgeSensor"}
    assert row["class_uid"] == 2004 and row["severity_id"] == 5


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        (ALERT.replace("externalId=A-1001 ", ""), "id"),
        (ALERT.replace(" src=10.20.1.5 suser=alice shost=ws-0042", ""), "entity"),
        (ALERT.replace("|9|", "|Unknown|"), "severity"),
    ],
)
def test_a_short_alert_is_kept_flagged_and_has_no_key(text: str, missing: str) -> None:
    row = normalize(template(), text)
    assert row["parse_status"] == "partial"
    assert f"alert_missing:{missing}" in row["parse_errors"]
    assert row["raw"] == text  # rule 5: never rejected, never changed
    assert "_alert" not in json.loads(row["unmapped"] or "{}")


def test_the_sensor_that_sent_it_is_not_the_subject() -> None:
    # Only the syslog header names a host: that is the sensor, not who the alert is about.
    text = ALERT.replace(" src=10.20.1.5 suser=alice shost=ws-0042", "")
    assert normalize(template(), text)["device_hostname"] == "sensor01"
    assert "alert_missing:entity" in normalize(template(), text)["parse_errors"]


def test_a_hostile_alert_line_never_raises() -> None:
    for text in ("CEF:0|" + "|" * 5_000, ALERT + " externalId=" + "x" * 10_240, ""):
        assert normalize(template(), text)["raw"] == text
