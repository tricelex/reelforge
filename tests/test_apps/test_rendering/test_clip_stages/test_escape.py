"""Tests for ffmpeg filtergraph escaping helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from server.apps.rendering.clip_stages.escape import (
    drawtext_escape,
    filter_path_escape,
)


def test_drawtext_escape_plain_text_unchanged() -> None:
    assert drawtext_escape('Amazing hook') == 'Amazing hook'


def test_drawtext_escape_apostrophe_splices_quotes() -> None:
    assert drawtext_escape("Here's why") == "Here'\\''s why"


def test_drawtext_escape_commas_and_colons_pass_through() -> None:
    """Commas/colons are safe inside single quotes — no escaping needed."""
    assert drawtext_escape('Tip 1: do this, now') == 'Tip 1: do this, now'


def test_drawtext_escape_percent_and_backslash() -> None:
    assert drawtext_escape('100% \\ done') == '100\\% \\\\ done'


def test_drawtext_escape_apostrophe_and_comma_combined() -> None:
    """The regression case: apostrophe + comma broke the filtergraph."""
    assert (
        drawtext_escape("It's huge, watch till the end")
        == "It'\\''s huge, watch till the end"
    )


def test_filter_path_escape_plain_path_unchanged() -> None:
    assert filter_path_escape('/fonts/Anton.ttf') == '/fonts/Anton.ttf'


def test_filter_path_escape_quote() -> None:
    assert filter_path_escape("/tmp/it's.ttf") == "/tmp/it'\\''s.ttf"


@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
def test_hook_overlay_with_apostrophe_keeps_quote_pairing(
    mock_resolve: MagicMock,
    mock_run: MagicMock,
) -> None:
    """Hook text with `'` and `,` must not split the filtergraph."""
    from server.apps.rendering.clip_stages.hook import HookStage

    mock_resolve.return_value = ('/fonts/Anton-Regular.ttf', 'Anton')
    mock_run.return_value = MagicMock(returncode=0)
    sc = MagicMock()
    sc.hook_enabled = True
    sc.hook_style = 'OVERLAY_TOP'
    sc.hook_font = 'ANTON'
    sc.hook_font_asset = None
    sc.hook_size = 60
    sc.hook_color = '#FFFFFF'
    sc.hook_bg_color = '#CC000000'
    sc.hook_animation = 'NONE'
    sc.hook_duration_sec = 3.0
    stage = HookStage(
        hook_text="Here's the truth, finally",
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    vf = mock_run.call_args[0][0]
    drawtext = vf[vf.index('-vf') + 1]
    assert "text='Here'\\''s the truth, finally'" in drawtext
    # The whole filter value must still be a single drawtext filter.
    assert drawtext.startswith('drawtext=')
