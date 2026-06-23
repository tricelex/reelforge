"""OpenAI Whisper transcription client."""

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import openai
from openai import APIConnectionError, APIStatusError, APITimeoutError

from server.common.exceptions import FatalProviderError, RetryableProviderError

logger = logging.getLogger('***REMOVED***.generation.clients.whisper')

WHISPER_COST_PER_MINUTE_USD = Decimal('0.006')
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_FATAL_STATUS = {401, 403, 422}


def calculate_cost(duration_sec: float) -> Decimal:
    """Return USD cost for a Whisper transcription at the given duration."""
    minutes = Decimal(str(duration_sec)) / Decimal(60)
    return (minutes * WHISPER_COST_PER_MINUTE_USD).quantize(Decimal('0.000001'))


def _raise_openai_error(exc: Exception) -> None:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        raise RetryableProviderError(str(exc), provider='openai') from exc
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status in _RETRYABLE_STATUS:
            raise RetryableProviderError(
                str(exc),
                provider='openai',
                status_code=status,
            ) from exc
        if status in _FATAL_STATUS:
            raise FatalProviderError(
                str(exc),
                provider='openai',
                error_code=str(status),
            ) from exc
        raise RetryableProviderError(
            str(exc),
            provider='openai',
            status_code=status,
        ) from exc
    raise RetryableProviderError(str(exc), provider='openai') from exc


def transcribe(audio_path: Path, api_key: str) -> dict[str, Any]:
    """Transcribe audio via OpenAI Whisper verbose_json API."""
    logger.info('whisper_transcribe_start', extra={'path': str(audio_path)})
    client = openai.OpenAI(api_key=api_key)
    try:
        with audio_path.open('rb') as audio_file:
            response = client.audio.transcriptions.create(
                model='whisper-1',
                file=audio_file,
                response_format='verbose_json',
                timestamp_granularities=['word', 'segment'],
            )
    except Exception as exc:
        _raise_openai_error(exc)

    if hasattr(response, 'model_dump'):
        result: dict[str, Any] = response.model_dump()
    else:
        result = dict(response)  # type: ignore[arg-type]

    duration = float(result.get('duration', 0))
    logger.info(
        'whisper_transcribe_complete',
        extra={
            'duration_sec': duration,
            'cost_usd': float(calculate_cost(duration)),
        },
    )
    return result
