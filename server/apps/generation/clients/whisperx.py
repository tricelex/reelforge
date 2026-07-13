"""Forced alignment via torchaudio (CPU) — replaces full whisperx for captions."""

import asyncio
import re
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


def _tokenize_words(text: str) -> list[str]:
    """Split transcript into word tokens for alignment."""
    return [w for w in re.findall(r"\w+(?:'\w+)?", text) if w]


def _load_mono_16k(audio_path: str) -> Any:
    """Load audio as mono float waveform at 16 kHz."""
    import torchaudio  # noqa: PLC0415

    waveform, sample_rate = torchaudio.load(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sample_rate != _SAMPLE_RATE:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            _SAMPLE_RATE,
        )
    return waveform.squeeze(0)


def _proportional_word_timings(
    words: list[str],
    duration: float,
) -> list[dict[str, Any]]:
    """Evenly spaced word timings (fallback when FA model path fails)."""
    if not words:
        return []
    slot = duration / len(words)
    return [
        {
            'word': word,
            'start': i * slot,
            'end': (i + 1) * slot,
            'score': 0.0,
        }
        for i, word in enumerate(words)
    ]


def _align_with_torchaudio(
    waveform: Any,
    words: list[str],
    device: str,
) -> list[dict[str, Any]]:
    """Run torchaudio MMS forced alignment; return word timing dicts."""
    import torch  # noqa: PLC0415
    from torchaudio.pipelines import MMS_FA as bundle  # noqa: PLC0415

    if not words:
        return []

    model = bundle.get_model()
    model.to(device)
    model.eval()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    with torch.inference_mode():
        emission, _ = model(waveform.to(device).unsqueeze(0))

    # MMS_FA expects lowercase words joined by '|'.
    transcript = '|'.join(w.lower() for w in words)
    token_spans = aligner(emission[0], tokenizer(transcript))
    ratio = waveform.size(0) / emission.size(1)
    timed: list[dict[str, Any]] = []
    for word, spans in zip(words, token_spans, strict=False):
        if not spans:
            continue
        start = float(spans[0].start * ratio / _SAMPLE_RATE)
        end = float(spans[-1].end * ratio / _SAMPLE_RATE)
        score = float(sum(t.score for t in spans) / max(1, len(spans)))
        timed.append({
            'word': word,
            'start': start,
            'end': end,
            'score': score,
        })
    return timed


def _align_blocking(
    audio_path: str,
    transcript_text: str,
    language: str,
    device: str,
) -> dict[str, Any]:
    """Run forced alignment in a worker thread."""
    _ = language  # language-specific packs can be added later
    waveform = _load_mono_16k(audio_path)
    duration = float(waveform.shape[0]) / _SAMPLE_RATE
    segments = _build_align_segments(transcript_text, duration)
    words = _tokenize_words(transcript_text)
    try:
        word_timings = _align_with_torchaudio(waveform, words, device)
        if len(word_timings) != len(words):
            word_timings = _proportional_word_timings(words, duration)
    except Exception:
        word_timings = _proportional_word_timings(words, duration)

    return {
        'segments': [
            {
                **segments[0],
                'words': word_timings,
            },
        ],
    }


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
        raise RuntimeError(f'Alignment failed: {exc}') from exc
