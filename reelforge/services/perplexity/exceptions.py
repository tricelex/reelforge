from __future__ import annotations


class PerplexityClientError(Exception):
    pass


class PerplexityAuthError(PerplexityClientError):
    pass


class PerplexityQuotaError(PerplexityClientError):
    pass


class PerplexityAPIError(PerplexityClientError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
