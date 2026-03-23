from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import openai

logger = logging.getLogger("reelforge.services.transcription")

# Whisper pricing: $0.006 per minute (as of 2026)
WHISPER_COST_PER_MINUTE_USD = Decimal("0.006")


@dataclass
class WhistlerTranscriptionResult:
    transcript_text: str
    transcript_json: dict[str, Any]
    duration_sec: float
    cost_usd: Decimal
    provider: str = "openai_whisper"


class WhisperTranscriptionService:
    def __init__(self, api_key: str) -> None:
        self._client = openai.OpenAI(api_key=api_key)

    def transcribe(self, video_path: Path) -> WhistlerTranscriptionResult:
        logger.info("Starting Whisper transcription", extra={"path": str(video_path)})

        with video_path.open("rb") as f:
            response = self._client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )

        response_dict = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        result = self._parse_response(response_dict)

        logger.info(
            "Whisper transcription completed",
            extra={
                "duration_sec": result.duration_sec,
                "cost_usd": float(result.cost_usd),
                "word_count": len(result.transcript_text.split()),
            },
        )
        return result

    def _parse_response(self, response: dict[str, Any]) -> WhistlerTranscriptionResult:
        duration = float(response.get("duration", 0))
        return WhistlerTranscriptionResult(
            transcript_text=response.get("text", ""),
            transcript_json=response,
            duration_sec=duration,
            cost_usd=self._calculate_cost(duration),
        )

    def _calculate_cost(self, duration_sec: float) -> Decimal:
        minutes = Decimal(str(duration_sec)) / Decimal("60")
        return (minutes * WHISPER_COST_PER_MINUTE_USD).quantize(Decimal("0.000001"))
