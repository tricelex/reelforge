class RetryableProviderError(Exception):
    """Provider error that can be retried (429, 5xx, timeout)."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class FatalProviderError(Exception):
    """Provider error requiring human intervention (content policy, bad prompt)."""

    def __init__(
        self,
        message: str,
        provider: str,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.error_code = error_code
