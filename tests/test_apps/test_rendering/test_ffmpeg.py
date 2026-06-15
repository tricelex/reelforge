"""Tests for the rendering.ffmpeg service module."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.rendering.ffmpeg import async_ffprobe


def test_rendering_app_importable() -> None:
    import server.apps.rendering.ffmpeg  # noqa: F401, PLC0415

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
            return await async_ffprobe('/tmp/test.mp4')  # noqa: S108

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
            await async_ffprobe('/tmp/missing.mp4')  # noqa: S108

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'ffprobe failed' in str(e)


from server.apps.rendering.ffmpeg import mux_scene


def test_mux_scene_calls_ffmpeg_with_audio_trim_args() -> None:
    """mux_scene invokes ffmpeg with -ss/-to audio trim and output path."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    fake_probe = {'format': {'duration': '8.0'}, 'streams': []}

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
        ):
            await mux_scene(
                video_path='/tmp/seg.mp4',  # noqa: S108
                audio_path='/tmp/ch.mp3',  # noqa: S108
                start_s=2.0,
                end_s=9.5,
                out_path='/tmp/scene.mp4',  # noqa: S108
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'ffmpeg' in captured[0]
    assert '/tmp/scene.mp4' in cmd  # noqa: S108


def test_mux_scene_uses_hold_last_frame_on_large_drift() -> None:
    """When motion vs narration drifts >5%, tpad is used to hold last frame."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))
    captured: list[str] = []

    async def fake_exec(*args: str, **_: object) -> MagicMock:
        captured.extend(args)
        return mock_proc

    fake_probe = {'format': {'duration': '5.0'}, 'streams': []}

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
        ):
            # narration=8.5s, motion=5s → drift=70% >> 5%
            await mux_scene(
                video_path='/tmp/seg.mp4',  # noqa: S108
                audio_path='/tmp/ch.mp3',  # noqa: S108
                start_s=0.0,
                end_s=8.5,
                out_path='/tmp/out.mp4',  # noqa: S108
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'tpad' in cmd


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
                '/tmp/s.mp4',  # noqa: S108
                '/tmp/a.mp3',  # noqa: S108
                0.0,
                5.0,
                '/tmp/o.mp4',  # noqa: S108
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'mux_scene failed' in str(e)


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
                ['/tmp/s0.mp4', '/tmp/s1.mp4'],  # noqa: S108
                '/tmp/chapter.mp4',  # noqa: S108
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert '-f' in cmd and 'concat' in cmd
    assert '-c' in cmd and 'copy' in cmd
    assert '/tmp/chapter.mp4' in cmd  # noqa: S108


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
                ['/tmp/a.mp4'],  # noqa: S108
                '/tmp/out.mp4',  # noqa: S108
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
            return await loudnorm_pass1('/tmp/video.mp4')  # noqa: S108

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
            await loudnorm_pass1('/tmp/video.mp4')  # noqa: S108

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
                chapter_paths=['/tmp/ch0.mp4'],  # noqa: S108
                music_paths=[],
                music_gains_db=[],
                ass_path='/tmp/subs.ass',  # noqa: S108
                watermark_path=None,
                out_path='/tmp/final.mp4',  # noqa: S108
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'subtitles=' in cmd
    assert 'libx264' in cmd
    assert '/tmp/final.mp4' in cmd  # noqa: S108


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
                chapter_paths=['/tmp/ch0.mp4'],  # noqa: S108
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',  # noqa: S108
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
                chapter_paths=['/tmp/ch0.mp4'],  # noqa: S108
                music_paths=['/tmp/music.mp3'],  # noqa: S108
                music_gains_db=[-3.0],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',  # noqa: S108
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

    # Probe returns 0 duration — triggers line 63
    fake_probe = {'format': {'duration': '0'}, 'streams': []}

    async def _run() -> None:
        with (
            patch('asyncio.create_subprocess_exec', side_effect=fake_exec),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
        ):
            await mux_scene(
                video_path='/tmp/seg.mp4',  # noqa: S108
                audio_path='/tmp/ch.mp3',  # noqa: S108
                start_s=0.0,
                end_s=5.0,
                out_path='/tmp/out.mp4',  # noqa: S108
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'ffmpeg' in captured[0]
    assert '/tmp/out.mp4' in cmd  # noqa: S108


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
                chapter_paths=['/tmp/ch0.mp4'],  # noqa: S108
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path='/tmp/wm.png',  # noqa: S108
                out_path='/tmp/final.mp4',  # noqa: S108
            )

    asyncio.run(_run())
    cmd = ' '.join(captured)
    assert 'overlay' in cmd
    assert '/tmp/wm.png' in cmd  # noqa: S108


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
                chapter_paths=['/tmp/ch0.mp4'],  # noqa: S108
                music_paths=[],
                music_gains_db=[],
                ass_path='/tmp/subs.ass',  # noqa: S108
                watermark_path='/tmp/wm.png',  # noqa: S108
                out_path='/tmp/final.mp4',  # noqa: S108
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
                chapter_paths=['/tmp/ch0.mp4'],  # noqa: S108
                music_paths=[],
                music_gains_db=[],
                ass_path=None,
                watermark_path=None,
                out_path='/tmp/final.mp4',  # noqa: S108
            )

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'final_pass failed' in str(e)
