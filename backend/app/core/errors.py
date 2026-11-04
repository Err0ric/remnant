"""Typed exceptions. The API layer maps these to HTTP responses."""

from typing import ClassVar


class AppError(Exception):
    """Base class for all application errors."""


class ConfigError(AppError):
    """Configuration is missing or invalid."""


class QueryRejectedError(AppError):
    """The guard refused a query (statement type, table, function, or parse)."""


class QueryFailedError(AppError):
    """The query was allowed but failed while running (bad column, type error).
    `engine_error`: DuckDB's own error class, for the server log."""

    engine_error: str | None = None


class QueryMemoryError(QueryFailedError):
    """The query needed more memory than its share; a narrower range may work (F46). A
    server limit, not a bad request: 503 (F63). `query` names the query for the log."""

    def __init__(self, message: str, query: str = "query") -> None:
        super().__init__(message)
        self.query = query


class QueryBusyError(AppError):
    """Too many queries already running; this one waited and got no slot (D79)."""

    retry_after_s = 5


class QueryTimeoutError(AppError):
    """The query ran longer than the configured timeout and was interrupted."""


class SourceRejectedError(AppError):
    """A source configuration was refused (path outside allowed roots, missing, duplicate)."""


class NotFoundError(AppError):
    """The requested object does not exist or is not visible to the caller."""


class AuthRequiredError(AppError):
    """No valid session or token was presented."""


class ForbiddenError(AppError):
    """Signed in, but the role does not allow this action."""


class CsrfError(AppError):
    """A cookie-authenticated write arrived without a matching CSRF token."""


class SetupRequiredError(AppError):
    """No administrator exists yet on a network bind; only setup is open."""


class SetupInvalidError(AppError):
    """The setup link is wrong, expired, or already used."""


class SetupClosedError(AppError):
    """An administrator already exists, so setup is permanently off."""


class LoginFailedError(AppError):
    """Wrong username or password. Deliberately does not say which."""


class RateLimitedError(AppError):
    """Too many failed attempts; retry later."""

    def __init__(self, message: str, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ConflictError(AppError):
    """The object already exists."""


class LastAdminError(AppError):
    """The change would leave no active administrator."""


class FirstUserAdminError(AppError):
    """The first account on an install without accounts must be an administrator."""


class LinkInvalidError(AppError):
    """An invite or reset link is wrong, expired, already used, or for a disabled account."""


class InteractiveRequiredError(AppError):
    """This action needs a signed-in browser session, not an API token."""


class ParamInvalidError(AppError):
    """A saved-search parameter is unknown, missing, or the wrong type."""


class TemplateInvalidError(AppError):
    """A template or draft does not validate, fails its tests, or cannot be approved."""


class SearchInvalidError(AppError):
    """A saved search definition is inconsistent (for example an undefined placeholder)."""


class PayloadTooLargeError(AppError):
    """An uploaded document is larger than allowed."""


class ProviderError(AppError):
    """The model provider failed, refused, or returned something invalid."""


class ProviderBusyError(ProviderError):
    """The model server is occupied: it answered busy, or no slot came free in time
    (ADR-0028). Not a fault; try again later."""

    def __init__(self, message: str, retry_after_s: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderOutputLimitError(ProviderError):
    """The model stopped at its output limit while thinking: setting Thinking to Off for the
    provider is the fix (owner, 2026-11-03: the page links admins straight to it; D192)."""


class ProviderUnreachableError(ProviderError):
    """No connection to the model server (refused, timed out, name not found)."""


class CallCancelledError(AppError):
    """The caller went away while the model call waited for a slot (ADR-0028 row 6)."""


class AnswerShapeError(ProviderError):
    """The model replied, but not in the required JSON shape (a caller may ask once more)."""


class ProviderConfigError(AppError):
    """The provider cannot be used as configured (disabled, or a cloud URL without TLS)."""


class ClassificationBlockedError(AppError):
    """A cloud provider was asked to see data from local-only sources (SPEC 6.2)."""

    def __init__(self, message: str, sources: list[str]) -> None:
        super().__init__(message)
        self.sources = sources


class CloudAckRequiredError(AppError):
    """Adding or pointing a provider at a cloud host needs an explicit acknowledgment."""


class RuleRejectedError(AppError):
    """A Sigma rule cannot be compiled or is refused as unsafe (ADR-0006)."""


class SsoRequiredError(AppError):
    """This account signs in with single sign-on; passwords are for administrators only."""


class SsoRefusedError(AppError):
    """A single sign-on attempt was refused (ADR-0013).

    `code` is one of a fixed set the sign-in page turns into a message; `reason` is for the
    audit log only and is never shown to the browser.
    """

    CODES = frozenset(
        {
            "expired",
            "invalid",
            "unavailable",
            "denied",
            "not_invited",
            "disabled",
            "not_in_group",
            "too_many_groups",
            "already_linked",
            "off",
        }
    )

    MESSAGES: ClassVar[dict[str, str]] = {
        "off": "Single sign-on is not turned on for this server",
        "unavailable": "The sign-in service cannot be reached right now. Try again shortly",
    }

    def __init__(self, code: str, reason: str) -> None:
        if code not in self.CODES:
            raise ValueError(f"unknown SSO refusal code {code!r}")
        # str(exc) is what an API caller sees; the reason stays in the audit log.
        super().__init__(self.MESSAGES.get(code, "Single sign-on did not complete"))
        self.code = code
        self.reason = reason


class UnsupportedMediaError(AppError):
    """The request body is in a format this endpoint does not take (OTLP protobuf, say)."""


# DuckDB errors whose text can quote values from the data (a string it could not convert,
# JSON it could not parse). Binder, catalog, and parser errors name columns, types, and
# functions from the server's own SQL, never event content.
_DATA_ERRORS = (
    "Conversion Error",
    "Invalid Input Error",
    "Out of Range Error",
    "Constraint Error",
    "Mismatch Type Error",
)


def safe_message(message: str, limit: int = 240) -> str:
    """An error message fit for the server log (owner, 2026-11-03): its first line; for
    errors that can quote data, cut at the first quote character and before DuckDB's
    "Input:" echo, so no value from a log line is written out."""
    text = (message.splitlines() or [""])[0]
    if text.startswith(_DATA_ERRORS) or "Input:" in text:
        cut = min((i for i in (text.find("'"), text.find('"'), text.find("Input:")) if i >= 0),
                  default=len(text))  # fmt: skip
        text = text[:cut].rstrip(" :.(") + (" [values not logged]" if cut < len(text) else "")
    return text[:limit]


def log_detail(exc: BaseException) -> dict[str, str]:
    """What a background failure logs: the error class, the engine's own error class when
    a query failed (BinderException, ConversionException, IOException...), and the safe
    message."""
    out = {"error": type(exc).__name__}
    engine = getattr(exc, "engine_error", None) or (
        type(exc.__cause__).__name__ if exc.__cause__ is not None else None
    )
    if engine:
        out["engine_error"] = str(engine)
    detail = safe_message(str(exc))
    if detail:
        out["detail"] = detail
    return out
