"""Application errors with stable HTTP mapping."""


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, details: list | dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ProviderUnavailable(AppError):
    status_code = 503
    code = "provider_unavailable"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"


class SplitLeakageError(AppError):
    status_code = 409
    code = "split_leakage"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
