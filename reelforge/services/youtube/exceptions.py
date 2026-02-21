from __future__ import annotations


class YouTubeClientError(Exception):
    pass


class YouTubeAuthError(YouTubeClientError):
    pass


class YouTubeQuotaError(YouTubeClientError):
    pass


class YouTubeAPIError(YouTubeClientError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
