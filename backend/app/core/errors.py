"""Typed exceptions. The API layer maps these to HTTP responses."""

from typing import ClassVar


class AppError(Exception):
    """Base class for all application errors."""


class ConfigError(AppError):
    """Configuration is missing or invalid."""


class QueryRejectedError(AppError):
    """The guard refused a query (statement type, table, function, or parse)."""


class QueryFailedError(AppError):
    """The query was allowed but failed while running (bad column, type error)."""


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
