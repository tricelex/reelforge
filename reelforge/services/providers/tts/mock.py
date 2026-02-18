from __future__ import annotations

import logging

from ***REMOVED***.services.base import BaseTTSProvider
from ***REMOVED***.services.dataclass import TTSResponse

logger = logging.getLogger("***REMOVED***.providers.tts.mock")


class MockTTSProvider(BaseTTSProvider):
    """Mock TTS provider for placeholder functionality.
    TODO: Replace with real implementations (ElevenLabs, OpenAI TTS, Azure TTS).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        logger.warning(f"MockTTSProvider initialized for: {name}")

    def synthesize(self, text: str, voice_id: str, **settings) -> TTSResponse:
        """Generate mock TTS audio.

        Args:
            text: Text to convert to speech
            voice_id: Voice ID to use
            **settings: Additional voice settings (stability, similarity, etc.)

        Returns:
            TTSResponse with mock audio data

        TODO: Replace with actual TTS API call
        """
        logger.warning(f"MockTTSProvider.synthesize called - text_length={len(text)}, voice_id={voice_id}")

        # Mock audio bytes (empty WAV header)
        mock_audio = b"RIFF\x00\x00\x00\x00WAVEfmt \x00\x00\x00\x00"

        # Rough estimation: 150 words per minute, 16 chars per word average
        estimated_duration = len(text) / 16 / 150 * 60

        return TTSResponse(
            audio_bytes=mock_audio,
            duration_sec=estimated_duration,
            provider=self.name,
            cost_usd=0.0,  # Mock cost
        )
