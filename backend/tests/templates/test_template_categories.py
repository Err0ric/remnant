"""Starter template categories (ADR-0045 Consequences): the empty-result lines group sources
by category and say what each could record, so a wrong category gives a wrong line. The
categories those lines name are pinned here; moving a template is a deliberate edit."""

from app.search.coverage import ADDRESS_COLUMNS, ORDER
from app.templates.loader import load_dir
from app.templates.registry import STARTER_DIR
from app.templates.tables import load_tables

TABLES, _ = load_tables(STARTER_DIR / "maps")
TEMPLATES, _ = load_dir(STARTER_DIR, TABLES)

EXPECTED = {
    "dns": ["dns_bind", "dns_powerdns", "dns_unbound", "dns_windows"],
    "network": ["cisco_asa", "cisco_ios", "fortinet_fortigate", "paloalto_traffic", "unifi"],
    "system": ["linux_systemd", "paloalto_system"],
    "findings": ["cef_alerts", "cef_generic", "leef_generic", "m365_alert", "paloalto_threat"],
    "inventory": ["proxmox_inventory"],
}


def test_every_starter_template_has_a_category_the_explanations_know() -> None:
    known = {*ORDER, "inventory"} - {"other"}
    for tid, template in TEMPLATES.items():
        assert template.category in known, tid


def test_pinned_categories() -> None:
    for category, ids in EXPECTED.items():
        got = sorted(t for t, tpl in TEMPLATES.items() if tpl.category == category)
        assert got == ids, category


def test_dns_and_firewall_templates_record_an_address() -> None:
    for tid in EXPECTED["dns"] + EXPECTED["network"]:
        fields = set(TEMPLATES[tid].mapping.fields)
        assert ADDRESS_COLUMNS & fields, tid
