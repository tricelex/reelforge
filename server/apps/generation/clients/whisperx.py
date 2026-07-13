"""WhisperX forced alignment via Python API (runs on GPU queue workers)."""

import asyncio
from typing import Any

_SAMPLE_RATE = 16000


def _build_align_segments(
    transcript_text: str,
    duration: float,
) -> list[dict[str, Any]]:
    """Build a single segment spanning the audio for forced alignment."""
    text = transcript_text.strip()
    if not text:
        msg = 'transcript_text is empty — cannot align audio without script'
        raise ValueError(msg)
    if duration <= 0:
        msg = f'audio duration must be positive, got {duration}'
        raise ValueError(msg)
    return [{'text': text, 'start': 0.0, 'end': duration}]


def _align_blocking(
    audio_path: str,
    transcript_text: str,
    language: str,
    device: str,
) -> dict[str, Any]:
    """Run WhisperX forced alignment in a worker thread."""
    import whisperx  # type: ignore[import-untyped]

    audio = whisperx.load_audio(audio_path)  # type: ignore[attr-defined]
    duration = len(audio) / _SAMPLE_RATE
    segments = _build_align_segments(transcript_text, duration)
    model_a, metadata = whisperx.load_align_model(  # type: ignore[attr-defined]
        language_code=language,
        device=device,
    )
    return whisperx.align(  # type: ignore[attr-defined,no-any-return]
        segments,
        model_a,
        metadata,
        audio,
        device,
    )


async def align(
    audio_path: str,
    transcript_text: str,
    language: str = 'en',
    device: str = 'cpu',
    compute_type: str = 'int8',
) -> dict[str, Any]:
    """Align known transcript text to audio; returns word-level timestamps."""
    _ = compute_type  # retained for stage config compatibility
    try:
        return await asyncio.to_thread(
            _align_blocking,
            audio_path,
            transcript_text,
            language,
            device,
        )
    except Exception as exc:
        raise RuntimeError(f'WhisperX failed: {exc}') from exc
