from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from reelforge.services.transcription.whisper import WhistlerTranscriptionResult
from reelforge.services.transcription.whisper import WhisperTranscriptionService


def test_whisper_service_parses_response() -> None:
    mock_response = {
        "text": "Hello world this is a test",
        "segments": [
            {
                "start": 0.0,
                "end": 2.5,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5},
                    {"word": "world", "start": 0.6, "end": 1.0},
                ],
            }
        ],
        "duration": 2.5,
        "language": "en",
    }

    with patch("openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = MagicMock(
            model_dump=lambda: mock_response
        )

        service = WhisperTranscriptionService(api_key="test-key")
        result = service._parse_response(mock_response)

    assert result.transcript_text == "Hello world this is a test"
    assert result.duration_sec == 2.5
    assert len(result.transcript_json["segments"]) == 1


def test_whisper_service_calculates_cost() -> None:
    service = WhisperTranscriptionService(api_key="test-key")
    cost = service._calculate_cost(duration_sec=60.0)
    # Whisper costs $0.006 per minute
    assert cost == Decimal("0.006")
