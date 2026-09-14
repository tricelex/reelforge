"""Word timings -> chunked SRT caption cues.

Mirrors the cue-chunking and SRT time-format conventions used by
server/apps/pipelines/stages/alignment.py, kept as a standalone
duplicate so this tool has zero Django dependency.
"""

from typing import Any

_DEFAULT_CHUNK_WORDS = 4


def normalize_words(
    words_raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map ElevenLabs forced-alignment words to {word, start, end}.

    Whitespace-only tokens are dropped — forced alignment emits them
    between words.
    """
    mapped: list[dict[str, Any]] = []
    for w in words_raw:
        token = str(w.get('text', w.get('word', '')))
        if not token.strip():
            continue
        mapped.append({
            'word': token,
            'start': float(w.get('start', 0)),
            'end': float(w.get('end', 0)),
        })
    return mapped


def chunk_words_into_cues(
    words: list[dict[str, Any]],
    chunk_size: int = _DEFAULT_CHUNK_WORDS,
) -> list[dict[str, Any]]:
    """Split word timings into short subtitle cues (start/end/text)."""
    cues: list[dict[str, Any]] = []
    for start_i in range(0, len(words), chunk_size):
        chunk = words[start_i : start_i + chunk_size]
        texts = [str(w.get('word', '')).strip() for w in chunk]
        text = ' '.join(t for t in texts if t)
        if not text:
            continue
        cues.append({
            'start': float(chunk[0]['start']),
            'end': float(chunk[-1]['end']),
            'text': text,
        })
    return cues


def fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT's HH:MM:SS,mmm, carrying rounding overflow."""
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'


def build_srt(cues: list[dict[str, Any]]) -> bytes:
    """Build a standard SRT file from a list of {start, end, text} cues."""
    blocks: list[str] = []
    for i, cue in enumerate(cues, start=1):
        start = fmt_srt_time(float(cue['start']))
        end = fmt_srt_time(float(cue['end']))
        text = str(cue['text']).strip()
        blocks.append(f'{i}\n{start} --> {end}\n{text}')
    return '\n\n'.join(blocks).encode()
