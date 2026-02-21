from __future__ import annotations


class GoogleTrendsClientError(Exception):
    pass


class GoogleTrendsAuthError(GoogleTrendsClientError):
    pass


class GoogleTrendsQuotaError(GoogleTrendsClientError):
    pass


class GoogleTrendsAPIError(GoogleTrendsClientError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
