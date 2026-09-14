"""Manual ElevenLabs v3 TTS + captions tool.

Run directly: `python -m scripts.elevenlabs.run_tts`. Edit the config
block below before each run — there are no CLI flags. Reads
ELEVENLABS_API_KEY from the environment (never hardcode it here).
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from scripts.elevenlabs.audio_tags import strip_audio_tags
from scripts.elevenlabs.captions import (
    build_srt,
    chunk_words_into_cues,
    normalize_words,
)
from scripts.elevenlabs.client import force_align, synthesize
from scripts.elevenlabs.script_source import ScriptChapter, load_chapters

# --- Configure before running ---
SCRIPT_PATH = Path('run_0b0237ce_longform_editor_package/docs/script.md')
VOICE_ID = ''
RUN_NAME: str | None = None  # None -> derived from script filename + time
OUT_DIR = Path('scripts/elevenlabs/runs')
MODEL_ID = 'eleven_v3'
STABILITY = 0.5
SIMILARITY_BOOST = 0.75
CHUNK_WORDS = 4
# ---------------------------------


def _resolve_run_dir() -> Path:
    """Return this run's output directory, deriving a name if unset."""
    name = RUN_NAME or (f'{SCRIPT_PATH.stem}_{datetime.now(UTC):%Y%m%d%H%M%S}')
    return OUT_DIR / name


async def _process_chapter(
    chapter: ScriptChapter,
    *,
    api_key: str,
    run_dir: Path,
    offset_s: float,
) -> tuple[list[dict[str, object]], float, int]:
    """Synthesize + align one chapter.

    Returns (offset word timings, this chapter's duration in seconds,
    character count of the tagged narration sent to TTS).
    """
    audio_bytes = await synthesize(
        text=chapter.text,
        voice_id=VOICE_ID,
        api_key=api_key,
        model_id=MODEL_ID,
        stability=STABILITY,
        similarity_boost=SIMILARITY_BOOST,
    )
    audio_path = run_dir / 'audio' / f'ch_{chapter.idx:03d}.mp3'
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(audio_bytes)

    clean_text = strip_audio_tags(chapter.text)
    alignment = await force_align(
        audio_bytes=audio_bytes,
        text=clean_text,
        api_key=api_key,
    )
    raw_words = alignment.get('words', [])
    words = normalize_words(raw_words if isinstance(raw_words, list) else [])
    offset_words = [
        {**w, 'start': w['start'] + offset_s, 'end': w['end'] + offset_s}
        for w in words
    ]
    span = max((float(w['end']) for w in words), default=0.0)
    return offset_words, span, len(chapter.text)


async def main() -> None:
    """Run the configured chapters through TTS + forced alignment."""
    api_key = os.environ.get('ELEVENLABS_API_KEY', '')
    if not api_key:
        msg = 'ELEVENLABS_API_KEY environment variable is not set'
        raise RuntimeError(msg)
    if not VOICE_ID:
        msg = 'Set VOICE_ID in the config block before running'
        raise RuntimeError(msg)

    chapters = load_chapters(SCRIPT_PATH)
    if not chapters:
        msg = f'No chapters found in {SCRIPT_PATH}'
        raise RuntimeError(msg)

    run_dir = _resolve_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    all_words: list[dict[str, object]] = []
    offset_s = 0.0
    char_counts: dict[str, int] = {}
    for chapter in chapters:
        offset_words, span, char_count = await _process_chapter(
            chapter,
            api_key=api_key,
            run_dir=run_dir,
            offset_s=offset_s,
        )
        all_words.extend(offset_words)
        offset_s += span
        char_counts[f'ch_{chapter.idx:03d}'] = char_count

    captions_dir = run_dir / 'captions'
    captions_dir.mkdir(parents=True, exist_ok=True)
    cues = chunk_words_into_cues(all_words, chunk_size=CHUNK_WORDS)
    (captions_dir / 'captions.srt').write_bytes(build_srt(cues))
    (captions_dir / 'words.json').write_text(json.dumps(all_words, indent=2))

    manifest = {
        'script_path': str(SCRIPT_PATH),
        'voice_id': VOICE_ID,
        'model_id': MODEL_ID,
        'stability': STABILITY,
        'similarity_boost': SIMILARITY_BOOST,
        'chapter_char_counts': char_counts,
        'generated_at': datetime.now(UTC).isoformat(),
    }
    (run_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Wrote run to {run_dir}')


if __name__ == '__main__':
    asyncio.run(main())
