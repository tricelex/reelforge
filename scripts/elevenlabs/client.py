"""Raw httpx client for ElevenLabs TTS + forced alignment (standalone).

Mirrors server/apps/generation/clients/elevenlabs.py's approach (raw
HTTP, no SDK) but kept independent so this tool has zero Django
dependency and no retry/queueing behavior — it's a manual, low-volume
tool; just re-run it on failure.
"""

import httpx

_BASE = 'https://api.elevenlabs.io/v1'


async def synthesize(
    *,
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = 'eleven_v3',
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bytes:
    """Synthesize text to audio via ElevenLabs. Returns raw MP3 bytes."""
    async with httpx.AsyncClient(timeout=120.0) as http_client:
        resp = await http_client.post(
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
    _raise_for_status(resp)
    return resp.content


async def force_align(
    *,
    audio_bytes: bytes,
    text: str,
    api_key: str,
) -> dict[str, object]:
    """Force-align audio to a known transcript via ElevenLabs.

    Returns {words: [{text, start, end, loss}, ...], characters: [...],
    loss}.
    """
    async with httpx.AsyncClient(timeout=600.0) as http_client:
        resp = await http_client.post(
            f'{_BASE}/forced-alignment',
            headers={'xi-api-key': api_key},
            data={'text': text},
            files={'file': ('audio.mp3', audio_bytes, 'audio/mpeg')},
        )
    _raise_for_status(resp)
    result: dict[str, object] = resp.json()
    return result


def _raise_for_status(resp: httpx.Response) -> None:
    """Raise RuntimeError with status + body snippet on a bad response."""
    if not resp.is_success:
        msg = f'ElevenLabs {resp.status_code}: {resp.text[:300]}'
        raise RuntimeError(msg)
