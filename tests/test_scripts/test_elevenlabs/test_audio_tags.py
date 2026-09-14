"""Tests for the standalone strip_audio_tags()."""

from scripts.elevenlabs.audio_tags import strip_audio_tags


def test_strip_audio_tags_no_tags_returns_text_unchanged() -> None:
    """Text with no tags passes through untouched."""
    assert strip_audio_tags('Rome was great once.') == 'Rome was great once.'


def test_strip_audio_tags_removes_single_tag() -> None:
    """A single bracket tag is removed."""
    result = strip_audio_tags('[sighs] Rome was great once.')
    assert result == 'Rome was great once.'


def test_strip_audio_tags_removes_multiple_tags() -> None:
    """Multiple tags across the text are all removed."""
    result = strip_audio_tags(
        '[whispers] Rome was great once. [sighs] Then it fell.',
    )
    assert result == 'Rome was great once. Then it fell.'


def test_strip_audio_tags_drops_tag_only_line() -> None:
    """A line that is only a tag disappears entirely, not a blank line."""
    result = strip_audio_tags('Rome was great once.\n[Pause]\nThen it fell.')
    assert result == 'Rome was great once.\nThen it fell.'
