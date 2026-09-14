"""Tests for strip_audio_tags()."""

from server.apps.pipelines.logic.audio_tags import strip_audio_tags


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


def test_strip_audio_tags_removes_adjacent_tags() -> None:
    """Back-to-back tags with no text between them collapse cleanly."""
    result = strip_audio_tags('[sighs][exhales] Rome fell.')
    assert result == 'Rome fell.'


def test_strip_audio_tags_drops_tag_only_line() -> None:
    """A line that is only a tag disappears entirely, not a blank line."""
    result = strip_audio_tags('Rome was great once.\n[Pause]\nThen it fell.')
    assert result == 'Rome was great once.\nThen it fell.'


def test_strip_audio_tags_collapses_extra_whitespace() -> None:
    """Removing a tag mid-sentence doesn't leave doubled spaces."""
    result = strip_audio_tags('Rome was great once.  [sighs]  Then it fell.')
    assert result == 'Rome was great once. Then it fell.'


def test_strip_audio_tags_empty_string_returns_empty_string() -> None:
    """Empty input returns empty output."""
    assert strip_audio_tags('') == ''
