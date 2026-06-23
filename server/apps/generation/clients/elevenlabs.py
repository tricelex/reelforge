"""ElevenLabs TTS provider client (raw HTTP — avoids SDK version pinning)."""

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_BASE = 'https://api.elevenlabs.io/v1'
_RETRYABLE = {429, 500, 502, 503, 504}


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
