from __future__ import annotations


class RedditClientError(Exception):
    pass


class RedditAuthError(RedditClientError):
    pass


class RedditQuotaError(RedditClientError):
    pass


class RedditAPIError(RedditClientError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
