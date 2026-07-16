"""Tests for the rendering.ffmpeg service module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.rendering.ffmpeg import async_ffprobe


def test_rendering_app_importable() -> None:
    import server.apps.rendering.ffmpeg  # noqa: F401

    assert True


def test_async_ffprobe_returns_parsed_json() -> None:
    fake_output = b'{"streams": [], "format": {"duration": "30.0"}}'
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(fake_output, b''))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await async_ffprobe('/tmp/test.mp4')

    result = asyncio.run(_run())
    assert result['format']['duration'] == '30.0'
    assert result['streams'] == []


def test_async_ffprobe_raises_on_nonzero_exit() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b'', b'no such file'))

    async def _run() -> None:
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            await async_ffprobe('/tmp/missing.mp4')

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'ffprobe failed' in str(e)


from server.apps.rendering.ffmpeg import mux_scene

_PROBE_MOTION = {
    'format': {'duration': '8.0'},
    'streams': [{'codec_type': 'video'}],
}
_PROBE_MEZZ_WITH_AUDIO = {
    'format': {'duration': '7.5'},
    'streams': [
        {'codec_type': 'video'},
        {'codec_type': 'audio'},
    ],
}
_PROBE_VIDEO_ONLY = {
    'format': {'duration': '6.0'},
    'streams': [{'codec_type': 'video'}],
}


def test_mux_scene_calls_ffmpeg_with_audio_trim_args() -> None:
    """mux_scene invokes ffmpeg with -ss/-to audio trim and output path."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(
                    side_effect=[_PROBE_MOTION, _PROBE_MEZZ_WITH_AUDIO],
                ),
            ),
        ):
            await mux_scene(
                video_path='/tmp/seg.mp4',
                audio_path='/tmp/ch.mp3',
                start_s=2.0,
                end_s=9.5,
                out_path='/tmp/scene.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'ffmpeg' in captured[0]
    assert '/tmp/scene.mp4' in cmd
    assert 'scale=1920:1080' in cmd
    assert 'pad=1920:1080' in cmd
    assert '-map' in captured
    assert '0:v:0' in captured
    assert '1:a:0' in captured
    assert '-t' in captured
    assert '7.500' in captured
    assert '-shortest' not in captured


def test_extract_ffmpeg_error_prefers_error_line_over_banner() -> None:
    from server.apps.rendering.ffmpeg import _extract_ffmpeg_error

    stderr = (
        'ffmpeg version 5.1.9 Copyright (c) 2000-2026\n'
        '  built with gcc 12\n'
        'Error opening input file /tmp/missing.mp4.\n'
        'Error opening input files: No such file or directory\n'
    )
    result = _extract_ffmpeg_error(stderr)
    assert 'Error opening input file' in result
    assert 'Copyright' not in result


def test_extract_ffmpeg_error_falls_back_to_tail() -> None:
    from server.apps.rendering.ffmpeg import _extract_ffmpeg_error

    stderr = 'banner stuff\n' + ('x' * 20) + 'TAIL_MARKER'
    result = _extract_ffmpeg_error(stderr, limit=40)
    assert result.endswith('TAIL_MARKER')


def test_concat_chapter_rejects_empty_segment_list() -> None:
    from server.apps.rendering.ffmpeg import concat_chapter

    async def _run() -> None:
        await concat_chapter([], '/tmp/out.mp4')

    try:
        asyncio.run(_run())
        raise AssertionError('expected ValueError')
    except ValueError as e:
        assert 'at least one segment' in str(e)


def test_mux_scene_uses_hold_last_frame_on_large_drift() -> None:
    """When motion vs narration drifts >5%, tpad is used to hold last frame."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    motion_probe = {
        'format': {'duration': '5.0'},
        'streams': [{'codec_type': 'video'}],
    }

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(
                    side_effect=[motion_probe, _PROBE_MEZZ_WITH_AUDIO],
                ),
            ),
        ):
            # narration=8.5s, motion=5s → drift=70% >> 5%
            await mux_scene(
                video_path='/tmp/seg.mp4',
                audio_path='/tmp/ch.mp3',
                start_s=0.0,
                end_s=8.5,
                out_path='/tmp/out.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'tpad' in cmd
    assert '0:v:0' in captured
    assert '1:a:0' in captured


def test_mux_scene_raises_on_ffmpeg_failure() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b'', b'error'))
    fake_probe = {'format': {'duration': '5.0'}, 'streams': []}

    async def _run() -> None:
        with (
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
        ):
            await mux_scene(
                '/tmp/s.mp4',
                '/tmp/a.mp3',
                0.0,
                5.0,
                '/tmp/o.mp4',
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'mux_scene failed' in str(e)


def test_mux_scene_rejects_non_positive_window() -> None:
    """mux_scene raises ValueError when end_s <= start_s."""

    async def _run() -> None:
        await mux_scene(
            video_path='/tmp/seg.mp4',
            audio_path='/tmp/ch.mp3',
            start_s=5.0,
            end_s=5.0,
            out_path='/tmp/scene.mp4',
        )

    try:
        asyncio.run(_run())
        raise AssertionError('expected ValueError')
    except ValueError as e:
        assert 'end_s > start_s' in str(e)


def test_mux_scene_raises_when_output_has_no_audio() -> None:
    """mux_scene fails fast if the encoded mezzanine is video-only."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))

    async def _run() -> None:
        with (
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(
                    side_effect=[_PROBE_MOTION, _PROBE_VIDEO_ONLY],
                ),
            ),
        ):
            await mux_scene(
                video_path='/tmp/seg.mp4',
                audio_path='/tmp/ch.mp3',
                start_s=0.0,
                end_s=5.0,
                out_path='/tmp/scene.mp4',
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'video-only output' in str(e)


from server.apps.rendering.ffmpeg import concat_chapter


def test_concat_chapter_calls_ffmpeg_concat_demuxer() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with patch('asyncio.create_subprocess_exec', side_effect=fake_exec):
            await concat_chapter(
                ['/tmp/s0.mp4', '/tmp/s1.mp4'],
                '/tmp/chapter.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert '-f' in cmd and 'concat' in cmd
    assert '-c' in cmd and 'copy' in cmd
    assert '/tmp/chapter.mp4' in cmd


def test_concat_chapter_raises_on_failure() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 2
    mock_proc.communicate = AsyncMock(return_value=(b'', b'fail'))

    async def _run() -> None:
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            await concat_chapter(
                ['/tmp/a.mp4'],
                '/tmp/out.mp4',
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'concat_chapter failed' in str(e)


import json as _json

from server.apps.rendering.ffmpeg import final_pass, loudnorm_pass1

_FAKE_STATS = {
    'input_i': '-23.5',
    'input_tp': '-2.1',
    'input_lra': '6.2',
    'input_thresh': '-33.5',
    'target_offset': '0.7',
}


def test_loudnorm_pass1_parses_json_from_stderr() -> None:
    stderr_output = (
        b'[Parsed_loudnorm]\n' + _json.dumps(_FAKE_STATS).encode() + b'\n'
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', stderr_output))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await loudnorm_pass1('/tmp/video.mp4')

    result = asyncio.run(_run())
    assert result['input_i'] == '-23.5'
    assert result['input_tp'] == '-2.1'


def test_loudnorm_pass1_raises_when_json_absent() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b'no json here'))

    async def _run() -> None:
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            await loudnorm_pass1('/tmp/video.mp4')

    try:
        asyncio.run(_run())
        raise AssertionError('expected ValueError')
    except ValueError as e:
        assert 'loudnorm JSON' in str(e)


def test_final_pass_calls_ffmpeg_with_subtitle_filter() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=[],
                music_gains_db=[],
                ass_path='/tmp/subs.ass',
                watermark_path=None,
                out_path='/tmp/final.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'subtitles=' in cmd
    assert 'libx264' in cmd
    assert '/tmp/final.mp4' in cmd


def test_final_pass_omits_overlay_when_no_watermark() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'overlay' not in cmd
    assert 'movie=' not in cmd


def test_final_pass_includes_amix_when_music_provided() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=['/tmp/music.mp3'],
                music_gains_db=[-3.0],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'amix' in cmd


def test_mux_scene_fallback_when_motion_dur_zero() -> None:
    """When probe returns duration 0, motion_dur falls back to narration_dur."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    zero_probe = {'format': {'duration': '0'}, 'streams': []}

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(
                    side_effect=[zero_probe, _PROBE_MEZZ_WITH_AUDIO],
                ),
            ),
        ):
            await mux_scene(
                video_path='/tmp/seg.mp4',
                audio_path='/tmp/ch.mp3',
                start_s=0.0,
                end_s=5.0,
                out_path='/tmp/out.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'ffmpeg' in captured[0]
    assert '/tmp/out.mp4' in cmd


def test_final_pass_with_watermark_and_no_music() -> None:
    """final_pass applies overlay complex filter with watermark and no music."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path='/tmp/wm.png',
                out_path='/tmp/final.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'overlay' in cmd
    assert '/tmp/wm.png' in cmd


def test_final_pass_with_watermark_and_subtitles_no_music() -> None:
    """final_pass with watermark+subtitles applies overlay then burns subs."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=[],
                music_gains_db=[],
                ass_path='/tmp/subs.ass',
                watermark_path='/tmp/wm.png',
                out_path='/tmp/final.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'overlay' in cmd
    assert 'subtitles=' in cmd


def test_final_pass_raises_on_ffmpeg_failure() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b'', b'encode failed'))

    async def _run() -> None:
        with (
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'final_pass failed' in str(e)


from server.apps.rendering.ffmpeg import (
    _build_complex_filter,
    _build_final_pass_cmd,
    _build_xfade_filter,
    _final_encode_args,
    _loudnorm_audio_filter,
    _run_ffmpeg_cmd,
    concat_chapter_with_transition,
)


def test_concat_chapter_with_transition_hard_cut_uses_stream_copy() -> None:
    """hard_cut delegates to concat_chapter (stream copy, no re-encode)."""

    async def _run() -> None:
        with patch(
            'server.apps.rendering.ffmpeg.concat_chapter',
            new=AsyncMock(),
        ) as mock_concat:
            await concat_chapter_with_transition(
                ['/tmp/a.mp4', '/tmp/b.mp4'],
                'hard_cut',
                0.5,
                '/tmp/out.mp4',
            )
            mock_concat.assert_awaited_once()

    asyncio.run(_run())


def test_concat_chapter_with_transition_single_segment_delegates() -> None:
    """A single segment can't cross-fade, so it delegates to concat_chapter."""

    async def _run() -> None:
        with patch(
            'server.apps.rendering.ffmpeg.concat_chapter',
            new=AsyncMock(),
        ) as mock_concat:
            await concat_chapter_with_transition(
                ['/tmp/a.mp4'],
                'cross_dissolve',
                0.5,
                '/tmp/out.mp4',
            )
            mock_concat.assert_awaited_once()

    asyncio.run(_run())


def test_concat_chapter_with_transition_cross_dissolve_builds_xfade() -> None:
    """cross_dissolve re-encodes with an xfade/acrossfade filter_complex."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=_PROBE_MEZZ_WITH_AUDIO),
            ),
        ):
            await concat_chapter_with_transition(
                ['/tmp/a.mp4', '/tmp/b.mp4'],
                'cross_dissolve',
                0.5,
                '/tmp/out.mp4',
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'xfade' in cmd
    assert 'acrossfade' in cmd
    assert 'transition=fade' in cmd
    assert '/tmp/out.mp4' in cmd


def test_concat_chapter_with_transition_normalizes_video_only_segment() -> None:
    """Video-only mezzanine segments get silent audio before xfade."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured_cmds: list[list[str]] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured_cmds.append(list(args))
        return mock_proc

    probes = {
        '/tmp/a.mp4': _PROBE_VIDEO_ONLY,
        '/tmp/b.mp4': _PROBE_MEZZ_WITH_AUDIO,
    }

    async def fake_probe(path: str) -> dict[str, object]:
        return probes.get(path, _PROBE_MEZZ_WITH_AUDIO)

    async def _run() -> None:
        with patch('asyncio.create_subprocess_exec', side_effect=fake_exec):
            with patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                side_effect=fake_probe,
            ):
                await concat_chapter_with_transition(
                    ['/tmp/a.mp4', '/tmp/b.mp4'],
                    'cross_dissolve',
                    0.5,
                    '/tmp/out.mp4',
                )

    asyncio.run(_run())
    assert len(captured_cmds) >= 2
    normalize_cmd = ' '.join(captured_cmds[0])
    assert 'anullsrc' in normalize_cmd
    assert '/tmp/a.mp4' in normalize_cmd
    xfade_cmd = ' '.join(captured_cmds[-1])
    assert 'xfade' in xfade_cmd
    assert 'acrossfade' in xfade_cmd


def test_probe_duration_returns_container_duration() -> None:
    from server.apps.rendering.ffmpeg import _probe_duration

    fake_probe = {'format': {'duration': '12.5'}, 'streams': []}

    async def _run() -> float:
        with patch(
            'server.apps.rendering.ffmpeg.async_ffprobe',
            new=AsyncMock(return_value=fake_probe),
        ):
            return await _probe_duration('/tmp/a.mp4')

    assert asyncio.run(_run()) == 12.5


def test_build_xfade_filter_chains_across_inputs() -> None:
    fc, v_out, a_out = _build_xfade_filter([5.0, 6.0, 7.0], 0.5)
    assert 'xfade=transition=fade' in fc
    assert 'acrossfade' in fc
    assert v_out == '[v2]'
    assert a_out == '[a2]'


def test_build_xfade_filter_uses_named_transition() -> None:
    fc, _, _ = _build_xfade_filter(
        [5.0, 6.0],
        0.5,
        transition='fade_black',
    )
    assert 'xfade=transition=fadeblack' in fc


def test_run_ffmpeg_cmd_uses_operation_label() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(
        return_value=(b'', b'matches no streams'),
    )

    async def _run() -> None:
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            await _run_ffmpeg_cmd(
                ['ffmpeg', '-version'],
                label='concat_chapter_with_transition',
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'concat_chapter_with_transition failed' in str(e)
        assert 'matches no streams' in str(e)


def test_final_pass_includes_sfx_in_amix() -> None:
    """SFX tracks are mixed alongside narration via amix."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
        ):
            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',
                sfx_paths=['/tmp/sfx.mp3'],
                sfx_gains_db=[-12.0],
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'amix' in cmd
    assert '/tmp/sfx.mp3' in cmd


def test_loudnorm_audio_filter_builds_string() -> None:
    result = _loudnorm_audio_filter(_FAKE_STATS)
    assert 'loudnorm=I=' in result
    assert 'measured_I=-23.5' in result


def test_build_complex_filter_watermark_and_music() -> None:
    fc, vmap, aout = _build_complex_filter(
        music_paths=['/tmp/music.mp3'],
        music_gains_db=[-3.0],
        sfx_paths=[],
        sfx_gains_db=[],
        ass_path='/tmp/subs.ass',
        watermark_path='/tmp/wm.png',
        wm_idx=2,
        loudnorm_af='loudnorm=I=-14',
    )
    assert 'overlay' in fc
    assert 'subtitles=' in fc
    assert 'amix' in fc
    assert vmap == '[vout]'
    assert aout == '[aout]'


def test_build_final_pass_cmd_simple_vf_path() -> None:
    cmd = _build_final_pass_cmd(
        inputs=['-i', '/tmp/concat.mp4'],
        music_paths=[],
        music_gains_db=[],
        sfx_paths=[],
        sfx_gains_db=[],
        ass_path='/tmp/subs.ass',
        watermark_path=None,
        loudnorm_af='loudnorm=I=-14',
        out_path='/tmp/final.mp4',
    )
    assert '-vf' in cmd
    assert 'subtitles=' in ' '.join(cmd)
    assert _final_encode_args('/tmp/final.mp4')[-1] == '/tmp/final.mp4'


def test_run_ffmpeg_cmd_success() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))

    async def _run() -> None:
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            await _run_ffmpeg_cmd(['ffmpeg', '-version'])

    asyncio.run(_run())


def test_final_pass_temp_file_cleanup() -> None:
    """final_pass removes concat temp file in finally block."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))

    async def _run() -> None:
        with (
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(
                    return_value=mock_proc,
                ),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.rendering.ffmpeg.loudnorm_pass1',
                new=AsyncMock(return_value=_FAKE_STATS),
            ),
            patch(
                'server.apps.rendering.ffmpeg.asyncio.to_thread',
                new=AsyncMock(),
            ) as mock_unlink,
        ):
            from server.apps.rendering.ffmpeg import final_pass

            await final_pass(
                chapter_paths=['/tmp/ch0.mp4'],
                music_paths=['/tmp/music.mp3'],
                music_gains_db=[-2.0],
                ass_path=None,
                watermark_path='/tmp/wm.png',
                out_path='/tmp/final.mp4',
            )
        mock_unlink.assert_awaited_once()

    asyncio.run(_run())
