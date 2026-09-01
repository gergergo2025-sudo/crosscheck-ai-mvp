"""Machine-readable service errors for the public API."""

from __future__ import annotations

from typing import Any


class CrossCheckError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    safe_message = "CrossCheck could not complete the request."

    def __init__(self, message: str | None = None, *, details: Any | None = None) -> None:
        super().__init__(message or self.safe_message)
        self.details = details


class RequestValidationError(CrossCheckError):
    status_code = 422
    code = "VALIDATION_ERROR"
    safe_message = "The request is invalid."


class RateLimitExceeded(CrossCheckError):
    """Anonymous client exceeded the configured request budget."""

    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
    safe_message = "Too many requests. Please retry later."

    def __init__(self, message: str | None = None, *, retry_after: int | None = None, details: Any | None = None) -> None:
        super().__init__(message, details=details)
        self.retry_after = retry_after


class ConcurrencyLimitExceeded(RateLimitExceeded):
    """No query worker is immediately available; work is rejected, not queued."""

    code = "CONCURRENCY_LIMIT_EXCEEDED"
    safe_message = "Too many queries are running. Please retry later."


class ModelConfigurationUnavailable(CrossCheckError):
    status_code = 503
    code = "MODEL_CONFIGURATION_UNAVAILABLE"
    safe_message = "No configured model provider is available."


class NoUsableModelAnswer(CrossCheckError):
    status_code = 502
    code = "NO_USABLE_MODEL_ANSWER"
    safe_message = "All selected model providers failed to return a usable answer."


class ReportPersistenceUnavailable(CrossCheckError):
    status_code = 503
    code = "REPORT_PERSISTENCE_UNAVAILABLE"
    safe_message = "The report could not be durably stored."


class FeedbackTargetNotFound(CrossCheckError):
    status_code = 404
    code = "REPORT_NOT_FOUND"
    safe_message = "The requested report does not exist."


class FeedbackClaimNotFound(CrossCheckError):
    status_code = 422
    code = "CLAIM_NOT_IN_REPORT"
    safe_message = "The selected claim does not belong to this report."
