from server.common.exceptions import FatalProviderError, RetryableProviderError


def test_retryable_error_stores_provider_and_status() -> None:
    err = RetryableProviderError(
        'rate limited',
        provider='fal_flux',
        status_code=429,
    )
    assert str(err) == 'rate limited'
    assert err.provider == 'fal_flux'
    assert err.status_code == 429


def test_fatal_error_stores_provider_and_code() -> None:
    err = FatalProviderError(
        'content policy',
        provider='fal_flux',
        error_code='SAFETY_FILTER',
    )
    assert str(err) == 'content policy'
    assert err.provider == 'fal_flux'
    assert err.error_code == 'SAFETY_FILTER'


def test_retryable_error_optional_fields_default_none() -> None:
    err = RetryableProviderError('timeout', provider='kling')
    assert err.status_code is None


def test_fatal_error_optional_fields_default_none() -> None:
    err = FatalProviderError('bad prompt', provider='openai')
    assert err.error_code is None
