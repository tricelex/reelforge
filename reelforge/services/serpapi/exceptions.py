from __future__ import annotations


class SerpApiError(Exception):
    """Base exception for all SerpAPI errors."""


class SerpApiRateLimitError(SerpApiError):
    """Raised when SerpAPI returns a 429 / rate-limit response."""


class SerpApiAuthError(SerpApiError):
    """Raised when SerpAPI returns an authentication error."""
