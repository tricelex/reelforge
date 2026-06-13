"""Domain exceptions for classifying provider errors."""


class RetryableProviderError(Exception):
    """Provider error that can be retried (429, 5xx, timeout)."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        """Initialise with a human-readable message and provider name."""
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class FatalProviderError(Exception):
    """Fatal provider error — requires human intervention to resolve."""

    def __init__(
        self,
        message: str,
        provider: str,
        error_code: str | None = None,
    ) -> None:
        """Initialise with message, provider name, and error code."""
        super().__init__(message)
        self.provider = provider
        self.error_code = error_code
