"""OTLP values found in the overnight QA run (F1, F2, F5, F7): non-finite and absurd
numbers, secrets past the 8 KB storage cut, and timestamps far in the future."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.sensitive import scan
from app.ingest.otlp import _num, _time, log_records, metric_records

KEY = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def s(v: str) -> dict[str, Any]:
    return {"stringValue": v}


def logs(prompt: str) -> dict[str, Any]:
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": s("claude-code")}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": str(int(datetime.now(UTC).timestamp() * 1e9)),
                                "attributes": [
                                    {"key": "event.name", "value": s("user_prompt")},
                                    {"key": "prompt", "value": s(prompt)},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


def cost(value: object) -> dict[str, Any]:
    return {
        "resourceMetrics": [
            {
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "claude_code.cost.usage",
                                "sum": {"dataPoints": [{"asDouble": value}]},
                            }
                        ]
                    }
                ]
            }
        ]
    }


def test_non_finite_numbers_are_dropped() -> None:
    assert _num("NaN") is None and _num("Infinity") is None and _num("-inf") is None
    assert _num("1.5") == 1.5 and _num(3) == 3


def test_cost_points_must_be_plausible() -> None:
    for bad in ("NaN", -75.5, 1e308):
        (rec,) = metric_records(cost(bad))
        assert rec["value"] is None, bad
    (rec,) = metric_records(cost(1.25))
    assert rec["value"] == 1.25


def test_secrets_past_the_storage_cut_are_still_found() -> None:
    for pad in (8_000, 8_200, 40_000):
        (rec,) = log_records(logs("A" * pad + " " + KEY), keep_content=False)
        assert rec["attr"].get("sensitive", {}).get("github_token") == 1, pad


def test_a_key_at_the_end_of_a_long_paste_is_found() -> None:
    assert scan("x" * 200_000 + " " + KEY).get("github_token") == 1


def test_future_timestamps_fall_back() -> None:
    far = int((datetime.now(UTC) + timedelta(days=365 * 3000)).timestamp() * 1e9)
    soon = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp() * 1e9)
    assert _time(far) is None
    assert _time(soon) is not None  # small clock skew is fine
