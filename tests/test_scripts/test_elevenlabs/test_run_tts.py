"""Tests for scripts/elevenlabs/run_tts.py."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.elevenlabs import run_tts


def _fa_result() -> dict[str, object]:
    """A 2-word forced-alignment result, chapter-relative (starts at 0).

    ElevenLabs aligns each chapter's audio file independently, so every
    raw result starts near 0 regardless of where the chapter sits in
    the full run — run_tts.py's own offset_s bookkeeping is what places
    it on the master timeline. Both mocked chapters reuse this same
    chapter-relative result on purpose.
    """
    return {
        'words': [
            {'text': 'word', 'start': 0.0, 'end': 0.4},
            {'text': 'two', 'start': 0.4, 'end': 0.8},
        ],
    }


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test sets its own config; nothing leaks between tests."""
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setattr(run_tts, 'VOICE_ID', 'voice-123')
    monkeypatch.setattr(run_tts, 'RUN_NAME', 'test-run')


def test_main_writes_audio_captions_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = tmp_path / 'script.md'
    script_path.write_text(
        '## Chapter 1: Opening\n\nFirst chapter text.\n\n'
        '## Chapter 2: Middle\n\nSecond chapter text.\n',
    )
    out_dir = tmp_path / 'runs'
    monkeypatch.setattr(run_tts, 'SCRIPT_PATH', script_path)
    monkeypatch.setattr(run_tts, 'OUT_DIR', out_dir)

    async def _inner() -> None:
        with (
            patch.object(
                run_tts,
                'synthesize',
                new=AsyncMock(side_effect=[b'audio-ch1', b'audio-ch2']),
            ),
            patch.object(
                run_tts,
                'force_align',
                new=AsyncMock(
                    side_effect=[_fa_result(), _fa_result()],
                ),
            ),
        ):
            await run_tts.main()

    asyncio.run(_inner())

    run_dir = out_dir / 'test-run'
    assert (run_dir / 'audio' / 'ch_001.mp3').read_bytes() == b'audio-ch1'
    assert (run_dir / 'audio' / 'ch_002.mp3').read_bytes() == b'audio-ch2'

    words = json.loads((run_dir / 'captions' / 'words.json').read_text())
    assert [w['word'] for w in words] == ['word', 'two', 'word', 'two']
    # Chapter 2's words are offset past chapter 1's 0.8s span.
    assert words[2]['start'] == pytest.approx(0.8)

    srt = (run_dir / 'captions' / 'captions.srt').read_text()
    assert 'word two word two' in srt

    manifest = json.loads((run_dir / 'manifest.json').read_text())
    assert manifest['voice_id'] == 'voice-123'
    assert manifest['model_id'] == 'eleven_v3'
    assert manifest['chapter_char_counts'] == {
        'ch_001': len('First chapter text.'),
        'ch_002': len('Second chapter text.'),
    }


def test_main_raises_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.setattr(run_tts, 'SCRIPT_PATH', tmp_path / 'script.md')
    (tmp_path / 'script.md').write_text('Some text.')

    with pytest.raises(RuntimeError, match='ELEVENLABS_API_KEY'):
        asyncio.run(run_tts.main())


def test_main_raises_without_voice_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_tts, 'VOICE_ID', '')
    monkeypatch.setattr(run_tts, 'SCRIPT_PATH', tmp_path / 'script.md')
    (tmp_path / 'script.md').write_text('Some text.')

    with pytest.raises(RuntimeError, match='VOICE_ID'):
        asyncio.run(run_tts.main())
