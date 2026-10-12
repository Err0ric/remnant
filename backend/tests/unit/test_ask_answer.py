"""AskAnswer accepts loosely shaped prose fields; the SQL stays strict."""

import pytest
from pydantic import ValidationError

from app.llm.agent import AskAnswer


def test_prose_fields_are_coerced_and_trimmed() -> None:
    a = AskAnswer.model_validate(
        {"sql": "SELECT 1", "explanation": None, "assumptions": "one guess"}
    )
    assert (a.explanation, a.assumptions) == ("", ["one guess"])
    b = AskAnswer.model_validate(
        {"sql": "SELECT 1", "explanation": "x" * 5000, "assumptions": ["y" * 900] * 12}
    )
    assert len(b.explanation) == 4000 and len(b.assumptions) == 10
    assert all(len(x) == 500 for x in b.assumptions)


def test_sql_is_still_required() -> None:
    with pytest.raises(ValidationError):
        AskAnswer.model_validate({"explanation": "no query"})
    with pytest.raises(ValidationError):
        AskAnswer.model_validate({"sql": "   "})
