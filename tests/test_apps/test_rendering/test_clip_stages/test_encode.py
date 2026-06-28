"""Tests for shared clip filter encode flags."""

from server.apps.rendering.clip_stages.encode import clip_filter_encode_args


def test_clip_filter_encode_args_reencodes_audio() -> None:
    args = clip_filter_encode_args(crf=28, preset='veryfast', fps=30)
    joined = ' '.join(args)
    assert '-c:a aac' in joined
    assert '-fps_mode cfr' in joined
    assert '-r 30' in joined
    assert 'copy' not in joined
