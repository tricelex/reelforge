"""Tests for scripts/elevenlabs/script_source.py."""

import json
from pathlib import Path

from scripts.elevenlabs.script_source import ScriptChapter, load_chapters


def test_load_chapters_from_markdown(tmp_path: Path) -> None:
    script_path = tmp_path / 'script.md'
    script_path.write_text(
        '# Script\n\n'
        '## Chapter 1: Night Opening\n\n'
        'You are tired of holding yourself against the world.\n\n'
        '## Chapter 2: Teaching Parable\n\n'
        '[sighs] Nothing is softer than water.\n',
    )
    chapters = load_chapters(script_path)
    assert chapters == [
        ScriptChapter(
            idx=1,
            title='Night Opening',
            text='You are tired of holding yourself against the world.',
        ),
        ScriptChapter(
            idx=2,
            title='Teaching Parable',
            text='[sighs] Nothing is softer than water.',
        ),
    ]


def test_load_chapters_from_markdown_with_no_headers_is_one_chapter(
    tmp_path: Path,
) -> None:
    script_path = tmp_path / 'script.txt'
    script_path.write_text('Just plain narration, no chapter headers.')
    chapters = load_chapters(script_path)
    assert chapters == [
        ScriptChapter(
            idx=1,
            title='',
            text='Just plain narration, no chapter headers.',
        ),
    ]


def test_load_chapters_from_json(tmp_path: Path) -> None:
    script_path = tmp_path / 'script.json'
    script_path.write_text(
        json.dumps([
            {'idx': 1, 'title': 'Night Opening', 'text': 'You are tired.'},
            {'idx': 2, 'title': 'Parable', 'text': '[sighs] Water.'},
        ]),
    )
    chapters = load_chapters(script_path)
    assert chapters == [
        ScriptChapter(idx=1, title='Night Opening', text='You are tired.'),
        ScriptChapter(idx=2, title='Parable', text='[sighs] Water.'),
    ]
