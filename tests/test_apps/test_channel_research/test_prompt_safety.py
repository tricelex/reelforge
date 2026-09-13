"""Tests for the ChannelSpec prompt-template render-safety checks."""

from server.apps.channel_research.logic.prompt_safety import (
    _context_for_stage,
    _dummy_base_context,
    _render_error,
)


def test_context_for_stage_editor_brief_uses_bespoke_context() -> None:
    context = _context_for_stage('editor_brief')
    assert context == {
        'topic': 'Sample Topic',
        'kind': 'longform',
        'facts_json': '{}',
    }


def test_context_for_stage_merges_base_and_extras() -> None:
    context = _context_for_stage('scene_breakdown')
    assert context is not None
    assert context['topic'] == 'Sample Topic'  # from the base context
    assert context['chapter']['idx'] == 0  # from the stage's extra
    assert context['hero_ratio'] == 0.15


def test_context_for_stage_unknown_stage_returns_none() -> None:
    assert _context_for_stage('not_a_real_stage') is None


def test_render_error_blank_template_is_skipped() -> None:
    assert _render_error('   ', {}) is None


def test_render_error_none_on_valid_template() -> None:
    context = _dummy_base_context()
    assert _render_error('Topic: {{ topic }}', context) is None


def test_render_error_reports_undefined_variable() -> None:
    context = _dummy_base_context()
    error = _render_error('{{ not_a_real_variable }}', context)
    assert error is not None
    assert 'undefined variable' in error


def test_render_error_reports_syntax_error() -> None:
    error = _render_error('{% if topic %}unterminated', {})
    assert error is not None
    assert 'syntax error' in error


def test_render_error_default_filter_tolerates_undefined() -> None:
    """A `| default(...)`-guarded optional variable is not flagged.

    That filter is the documented way to write an optional variable.
    """
    context = _dummy_base_context()
    error = _render_error(
        "{{ traditions | default('open') }}",
        context,
    )
    assert error is None
