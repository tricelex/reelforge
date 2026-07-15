"""ElevenLabs provider client (raw HTTP — avoids SDK version pinning).

Covers TTS synthesis, Scribe speech-to-text with diarization, and
forced alignment of known transcripts to audio.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_BASE = 'https://api.elevenlabs.io/v1'
_RETRYABLE = {429, 500, 502, 503, 504}
SCRIBE_COST_PER_MINUTE_USD = Decimal('0.00367')


async def synthesize(
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = 'eleven_multilingual_v2',
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bytes:
    """Synthesize text to audio. Returns raw MP3 bytes."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f'{_BASE}/text-to-speech/{voice_id}',
            headers={
                'xi-api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'audio/mpeg',
            },
            json={
                'text': text,
                'model_id': model_id,
                'voice_settings': {
                    'stability': stability,
                    'similarity_boost': similarity_boost,
                },
            },
        )

    if resp.status_code in _RETRYABLE:
        raise RetryableProviderError(
            f'ElevenLabs {resp.status_code}',
            provider='elevenlabs',
            status_code=resp.status_code,
        )
    if resp.status_code == 422:
        raise FatalProviderError(
            f'ElevenLabs validation error: {resp.text}',
            provider='elevenlabs',
            error_code='validation',
        )
    if not resp.is_success:
        raise RetryableProviderError(
            f'ElevenLabs {resp.status_code}: {resp.text[:200]}',
            provider='elevenlabs',
            status_code=resp.status_code,
        )
    return resp.content


def calculate_transcription_cost(duration_sec: float) -> Decimal:
    """Return USD cost for a Scribe transcription at the given duration."""
    minutes = Decimal(str(duration_sec)) / Decimal(60)
    return (minutes * SCRIBE_COST_PER_MINUTE_USD).quantize(Decimal('0.000001'))


async def transcribe(
    audio_path: Path,
    api_key: str,
    model_id: str = 'scribe_v2',
) -> dict[str, Any]:
    """Transcribe audio with speaker diarization via ElevenLabs Scribe.

    Returns {text, words: [{text, start, end, speaker_id, ...}],
    language_code, audio_duration_secs}.
    """
    with audio_path.open('rb') as audio_file:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f'{_BASE}/speech-to-text',
                headers={'xi-api-key': api_key},
                data={
                    'model_id': model_id,
                    'diarize': 'true',
                    'timestamps_granularity': 'word',
                },
                files={'file': (audio_path.name, audio_file, 'audio/mpeg')},
            )

    _raise_for_status(resp)
    result: dict[str, Any] = resp.json()
    return result


def _raise_for_status(resp: httpx.Response) -> None:
    """Map ElevenLabs HTTP errors to provider exceptions."""
    if resp.status_code in _RETRYABLE:
        raise RetryableProviderError(
            f'ElevenLabs {resp.status_code}',
            provider='elevenlabs',
            status_code=resp.status_code,
        )
    if resp.status_code == 422:
        raise FatalProviderError(
            f'ElevenLabs validation error: {resp.text}',
            provider='elevenlabs',
            error_code='validation',
        )
    if not resp.is_success:
        raise RetryableProviderError(
            f'ElevenLabs {resp.status_code}: {resp.text[:200]}',
            provider='elevenlabs',
            status_code=resp.status_code,
        )


async def force_align(
    audio_path: Path,
    text: str,
    api_key: str,
) -> dict[str, Any]:
    """Force-align audio to a known transcript via ElevenLabs.

    Returns {words: [{text, start, end, loss}, ...], characters: [...],
    loss}.
    """
    with audio_path.open('rb') as audio_file:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f'{_BASE}/forced-alignment',
                headers={'xi-api-key': api_key},
                data={'text': text},
                files={
                    'file': (audio_path.name, audio_file, 'audio/mpeg'),
                },
            )

    _raise_for_status(resp)
    result: dict[str, Any] = resp.json()
    return result
