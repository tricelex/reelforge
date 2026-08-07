from server.apps.clips.logic.constants import (
    CandidateStatus,
    CaptionStyle,
    HookStyle,
    PostStatus,
    ProgressBarPosition,
    RenderFormat,
    RenderMode,
    WatermarkPosition,
    WatermarkType,
    render_format_dimensions,
)
from server.apps.clips.logic.events import ClipCandidatesCreated


def test_render_mode_values() -> None:
    assert RenderMode.SMART_CROP == 'SMART_CROP'
    assert RenderMode.CENTER_CROP == 'CENTER_CROP'
    assert RenderMode.SPATIAL_STACK == 'SPATIAL_STACK'


def test_render_format_values() -> None:
    assert RenderFormat.VERTICAL_9_16 == 'VERTICAL_9_16'
    assert RenderFormat.LANDSCAPE_16_9 == 'LANDSCAPE_16_9'
    assert RenderFormat.SQUARE_1_1 == 'SQUARE_1_1'


def test_render_format_dimensions() -> None:
    assert render_format_dimensions(RenderFormat.VERTICAL_9_16) == (1080, 1920)
    assert render_format_dimensions(RenderFormat.LANDSCAPE_16_9) == (
        1920,
        1080,
    )
    assert render_format_dimensions(RenderFormat.SQUARE_1_1) == (1080, 1080)


def test_render_format_dimensions_unknown_defaults_to_vertical() -> None:
    assert render_format_dimensions('BOGUS') == (1080, 1920)


def test_candidate_status_values() -> None:
    expected = {
        'PROPOSED',
        'APPROVED',
        'REJECTED',
        'RENDERING',
        'RENDERED',
        'DISTRIBUTING',
        'DISTRIBUTED',
    }
    assert set(CandidateStatus.values) == expected


def test_clip_arrangement_and_beat_roles() -> None:
    from server.apps.clips.logic.constants import (
        CLIP_BEAT_PLAYBACK_ORDER,
        ClipArrangement,
        ClipBeatRole,
    )

    assert ClipArrangement.CONTIGUOUS == 'contiguous'
    assert ClipArrangement.COLD_OPEN == 'cold_open'
    assert ClipBeatRole.HOOK == 'hook'
    assert CLIP_BEAT_PLAYBACK_ORDER == ('hook', 'story', 'payoff')


def test_caption_style_values() -> None:
    assert 'WORD_BY_WORD' in CaptionStyle.values
    assert 'EMOJI_ACCENT' in CaptionStyle.values


def test_hook_style_values() -> None:
    assert HookStyle.TITLE_CARD == 'TITLE_CARD'


def test_post_status_values() -> None:
    assert PostStatus.PENDING == 'PENDING'
    assert PostStatus.POSTED == 'POSTED'


def test_watermark_position_values() -> None:
    assert WatermarkPosition.BOTTOM_RIGHT == 'BOTTOM_RIGHT'


def test_progress_bar_position_values() -> None:
    assert ProgressBarPosition.TOP == 'TOP'
    assert ProgressBarPosition.BOTTOM == 'BOTTOM'


def test_watermark_type_values() -> None:
    assert WatermarkType.IMAGE == 'IMAGE'
    assert WatermarkType.TEXT == 'TEXT'


def test_clip_candidates_created_event() -> None:
    event = ClipCandidatesCreated(run_id='abc', candidate_count=5)
    assert event.run_id == 'abc'
    assert event.candidate_count == 5
