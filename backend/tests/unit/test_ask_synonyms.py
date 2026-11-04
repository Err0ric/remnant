"""D191 (owner, 2026-11-03): "how many failed logins to microsoft today?" went to the model:
"logins" did not meet "sign-ins" and "microsoft" met nothing. Each synonym form must rank
the library query it names first (evals/nl_queries/synonyms.yaml)."""

from pathlib import Path

import pytest
import yaml

from app.search.ask_route import PHRASES, rank, words
from app.search.library import LIBRARY_DIR, Library, load_dir

SUITE = Path(__file__).resolve().parents[2] / "evals" / "nl_queries" / "synonyms.yaml"
CASES = yaml.safe_load(SUITE.read_text())["questions"]
LIB = Library(load_dir(LIBRARY_DIR))
SEEN = {t for p in LIB.packs for q in p.queries for t in q.requires}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_each_form_ranks_its_query_first(case: dict[str, str]) -> None:
    top = rank(case["question"], LIB, SEEN)
    assert top, case
    assert top[0].ref == case["library"], [(c.ref, c.score) for c in top[:3]]


def test_every_form_has_a_question() -> None:
    asked = " ".join(c["question"].lower() for c in CASES)
    for pattern, _ in PHRASES:
        assert pattern.search(asked), pattern.pattern


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("logins", "sign-ins"), ("log-ins", "signins"), ("log in", "sign in"),
        ("authentications", "sign-ins"), ("microsoft", "m365"), ("office 365", "o365"),
        ("entra id", "azure ad"), ("azure active directory", "microsoft 365"),
        ("firewall", "palo alto"), ("pan-os", "pan"), ("vpn", "global protect"),
        ("claude code", "coding agent"), ("ai agents", "cowork"), ("claude", "agent"),
    ],
)  # fmt: skip
def test_forms_are_one_word(a: str, b: str) -> None:
    assert words(a) == words(b) and words(a)


def test_accessing_means_files_commands_and_domains() -> None:
    """D196: what an agent is "accessing" (or touching, opening) is its files, commands,
    and web domains, so those three queries come first."""
    for verb in ("accessing", "touching", "opening"):
        top = rank(f"What is dana {verb} with Claude Code?", LIB, SEEN)
        assert {c.ref for c in top[:3]} == {
            "ai_agents/agents_files_by_person",
            "ai_agents/agents_commands_by_person",
            "ai_agents/agents_web_by_person",
        }, [(c.ref, c.score) for c in top[:5]]
