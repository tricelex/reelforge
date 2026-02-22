from __future__ import annotations

import logging
from typing import Any

from elevenlabs import ElevenLabs
from elevenlabs import VoiceSettings

from reelforge.services.base import BaseTTSProvider
from reelforge.services.dataclass import TTSResponse

logger = logging.getLogger("reelforge.providers.tts")

# ElevenLabs Creator tier pricing (~$0.24 per 1,000 chars)
_COST_PER_CHAR = 0.00024

# Default model — multilingual v2 for quality; swap to eleven_turbo_v2_5 for speed
_DEFAULT_MODEL = "eleven_multilingual_v2"

# Approximate speaking rate used for duration estimation
_WORDS_PER_MINUTE = 150
_CHARS_PER_WORD = 5.5  # average English word length including space


class ElevenLabsProvider(BaseTTSProvider):
    """ElevenLabs TTS provider.

    Docs: https://elevenlabs.io/docs/api-reference/text-to-speech
    """

    name = "elevenlabs"

    def __init__(self, api_key: str, default_model: str = _DEFAULT_MODEL) -> None:
        self.client = ElevenLabs(api_key=api_key)
        self.default_model = default_model

    def synthesize(self, text: str, voice_id: str, **settings: Any) -> TTSResponse:
        """Convert text to speech using ElevenLabs.

        Args:
            text: Text to synthesize.
            voice_id: ElevenLabs voice ID.
            **settings: Optional overrides — stability, similarity_boost, style,
                        use_speaker_boost, model_id.

        Returns:
            TTSResponse with MP3 audio bytes, estimated duration, and cost.
        """
        model_id: str = settings.pop("model_id", self.default_model)
        voice_settings = VoiceSettings(
            stability=float(settings.get("stability", 0.5)),
            similarity_boost=float(settings.get("similarity_boost", settings.get("similarity", 0.8))),
            style=float(settings.get("style", 0.3)),
            use_speaker_boost=bool(settings.get("use_speaker_boost", True)),
        )

        logger.info(
            "ElevenLabs synthesize called",
            extra={
                "voice_id": voice_id,
                "model_id": model_id,
                "text_length": len(text),
                "stability": voice_settings.stability,
                "similarity_boost": voice_settings.similarity_boost,
            },
        )

        audio_chunks = self.client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            voice_settings=voice_settings,
        )
        audio_bytes = b"".join(audio_chunks)

        # Estimate duration from character count
        word_count = len(text) / _CHARS_PER_WORD
        duration_sec = word_count / _WORDS_PER_MINUTE * 60.0

        cost_usd = len(text) * _COST_PER_CHAR

        logger.info(
            "ElevenLabs synthesis complete",
            extra={
                "voice_id": voice_id,
                "audio_bytes": len(audio_bytes),
                "estimated_duration_sec": round(duration_sec, 2),
                "cost_usd": round(cost_usd, 6),
            },
        )

        return TTSResponse(
            audio_bytes=audio_bytes,
            duration_sec=duration_sec,
            provider=self.name,
            cost_usd=cost_usd,
        )
