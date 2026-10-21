"""safeyaml: no object tags, no aliases (YAML from people and uploads)."""

import pytest
import yaml

from app.core import safeyaml


def test_plain_documents_load() -> None:
    assert safeyaml.load("a: [1, 2]\nb: {c: d}\n") == {"a": [1, 2], "b": {"c": "d"}}


@pytest.mark.parametrize(
    "text",
    [
        "a: &x [1]\nb: *x\n",
        "!!python/object/apply:os.system ['true']\n",
    ],
)
def test_aliases_and_tags_are_refused(text: str) -> None:
    with pytest.raises(yaml.YAMLError):
        safeyaml.load(text)


@pytest.mark.parametrize(
    "text",
    [
        "[" * 5_000 + "]" * 5_000,
        "a: " + "{b: " * 100 + "1" + "}" * 100,
        "n: " + "9" * 5_000,
        "d: 2026-02-30",
    ],
)
def test_deep_or_unbuildable_documents_are_yaml_errors(text: str) -> None:
    with pytest.raises(yaml.YAMLError):
        safeyaml.load(text)
