from __future__ import annotations


class ExplodingTopicsClientError(Exception):
    pass


class ExplodingTopicsAuthError(ExplodingTopicsClientError):
    pass


class ExplodingTopicsQuotaError(ExplodingTopicsClientError):
    pass


class ExplodingTopicsAPIError(ExplodingTopicsClientError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
