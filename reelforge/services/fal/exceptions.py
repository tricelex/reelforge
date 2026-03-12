from __future__ import annotations


class FalAiError(Exception):
    """Base exception for all Fal.ai errors."""


class FalAiRateLimitError(FalAiError):
    """Raised when Fal.ai returns a 429 / rate-limit response."""


class FalAiAuthError(FalAiError):
    """Raised when Fal.ai returns an authentication error."""
