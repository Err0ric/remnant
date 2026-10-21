"""Sensitive-data signals count categories, never return text (ADR-0015 row 13)."""

from app.ai.sensitive import scan


def test_categories_are_found_and_counted() -> None:
    text = (
        "my ssn is 123-45-6789 and card 4111 1111 1111 1111, key AKIAABCDEFGHIJKLMNOP "
        "token ghp_"
        + "a" * 36
        + " and sk-ant-"
        + "b" * 30
        + "\n-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "password=hunter2xx"
    )
    got = scan(text)
    assert got == {
        "us_ssn": 1,
        "payment_card": 1,
        "aws_access_key": 1,
        "github_token": 1,
        "anthropic_key": 1,
        "private_key": 1,
        "password_assignment": 1,
    }


def test_ordinary_text_and_near_misses_are_clean() -> None:
    assert scan("order 1234567890123 shipped", "000-12-3456", "4111 1111 1111 1112", None, 42) == {}
    assert scan("call 555-123-4567 tomorrow; version 1.2.3") == {}


def test_long_input_is_bounded() -> None:
    # Only the first 48 KB and last 16 KB are read: the middle of a huge value is skipped.
    assert scan("x" * 1_000_000 + " 123-45-6789 " + "x" * 1_000_000) == {}
    assert scan("x" * 2_000_000 + " 123-45-6789") == {"us_ssn": 1}  # the tail is read
