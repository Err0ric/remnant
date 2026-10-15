"""The shipped AI catalog loads, and domain rules hold (ADR-0015 row 1)."""

import pytest
from pydantic import ValidationError

from app.ai.catalog import ServiceDef, shipped


def test_catalog_loads_with_unique_ids_and_valid_domains() -> None:
    items = shipped()
    assert len(items) >= 30
    domains = [d for s in items for d in s.domains]
    assert len(domains) == len(set(domains)), "a domain listed under two services"


@pytest.mark.parametrize(
    "domain", ["a' OR 1=1 --", "localhost", "-bad.com", "x..y.com", "UPPER.example.c"]
)
def test_domain_rules(domain: str) -> None:
    with pytest.raises(ValidationError):
        ServiceDef(id="x1", name="X", kind="chat", domains=(domain,))


def test_domains_are_normalized() -> None:
    assert ServiceDef(id="x1", name="X", kind="chat", domains=("Chat.Example.COM.",)).domains == (
        "chat.example.com",
    )
