"""Rule logsource to template matching (ADR-0006 row 2)."""

import pytest

from app.detect.logsource import LogSource, applies

WIN_SECURITY = LogSource(product="windows", service="security")
WIN_SYSMON_PROC = LogSource(product="windows", category="process_creation")
LINUX = LogSource(product="linux")


@pytest.mark.parametrize(
    ("rule", "declared", "expected"),
    [
        ({"product": "windows", "service": "security"}, [WIN_SECURITY], True),
        ({"product": "windows"}, [WIN_SECURITY], True),  # general rule, specific source
        ({"product": "windows", "service": "security"}, [LogSource(product="windows")], False),
        ({"product": "windows", "service": "system"}, [WIN_SECURITY], False),
        ({"product": "windows", "category": "process_creation"}, [WIN_SECURITY], False),
        (
            {"product": "windows", "category": "process_creation"},
            [WIN_SECURITY, WIN_SYSMON_PROC],
            True,
        ),
        ({"product": "linux", "service": "auditd"}, [LINUX], False),
        ({"category": "firewall"}, [LogSource(category="firewall", product="paloalto")], True),
        ({"category": "firewall"}, [LINUX], False),
        ({}, [WIN_SECURITY, LINUX], False),  # no logsource: runs nowhere
        ({"definition": "x"}, [LINUX], False),
        ({"product": "Windows", "service": " Security "}, [WIN_SECURITY], True),  # case
        ({"product": 5}, [LINUX], False),
        ({"product": "windows", "service": "sysmon"}, [LogSource("windows", "*")], True),
        ({"product": "windows", "category": "dns_query"}, [LogSource("windows", "*")], False),
        ({"product": "windows", "category": "dns_query"}, [LogSource("windows", None, "*")], True),
        ({"product": "linux", "service": "auth"}, [LogSource("windows", "*")], False),
    ],
)
def test_rule_applies_only_when_a_declared_entry_covers_every_field(
    rule: dict[str, object], declared: list[LogSource], expected: bool
) -> None:
    assert applies(LogSource.from_mapping(rule), declared) is expected


def test_label() -> None:
    assert WIN_SECURITY.label() == "product: windows / service: security"


def test_starter_templates_declare_logsources_and_star_never_names_a_product() -> None:
    from pathlib import Path

    import pydantic

    from app.core import safeyaml
    from app.templates.validator import SigmaLogSource, Template

    root = Path(__file__).resolve().parents[3] / "templates" / "starter"
    declared = {
        p.stem: Template.model_validate(safeyaml.load(p.read_text("utf-8"))).sigma.logsource
        for p in root.glob("*.yaml")
    }
    for tid in ("windows_evtx", "windows_nxlog_json", "windows_snare", "windows_winlogbeat"):
        sources = [LogSource(e.product, e.service, e.category) for e in declared[tid]]
        assert applies(LogSource("windows", "security"), sources)
        assert applies(LogSource("windows", None, "process_creation"), sources)
        assert not applies(LogSource("linux"), sources)
    assert applies(
        LogSource("linux"),
        [LogSource(e.product, e.service, e.category) for e in declared["linux_sshd"]],
    )
    assert declared["cef_generic"] == []
    with pytest.raises(pydantic.ValidationError):
        SigmaLogSource(product="*")
    with pytest.raises(pydantic.ValidationError):
        SigmaLogSource()
