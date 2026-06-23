import pathlib
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from server.apps.assets.logic.events import LibraryAssetIngested
from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.assets.tasks import (
    _ffprobe,
    _run_loudness,
    _transcode,
    handle_library_asset_ingested,
    ingest_library_asset,
)
from server.common.exceptions import FatalProviderError, RetryableProviderError

_AUDIO_PROBE = {
    'streams': [
        {
            'codec_type': 'audio',
            'codec_name': 'mp3',
            'channels': 2,
            'channel_layout': 'stereo',
            'pix_fmt': None,
            'width': None,
            'height': None,
            'r_frame_rate': None,
        },
    ],
    'format': {'duration': '180.5', 'format_name': 'mp3'},
}

_VIDEO_PROBE = {
    'streams': [
        {
            'codec_type': 'video',
            'codec_name': 'h264',
            'width': 1920,
            'height': 1080,
            'r_frame_rate': '30/1',
            'pix_fmt': 'yuv420p',
            'channels': None,
            'channel_layout': None,
        },
        {
            'codec_type': 'audio',
            'codec_name': 'aac',
            'channels': 2,
            'channel_layout': 'stereo',
            'pix_fmt': None,
            'width': None,
            'height': None,
            'r_frame_rate': None,
        },
    ],
    'format': {'duration': '30.0', 'format_name': 'mp4'},
}

_PNG_ALPHA_PROBE = {
    'streams': [
        {
            'codec_type': 'video',
            'codec_name': 'png',
            'pix_fmt': 'yuva8p',
            'width': 200,
            'height': 200,
            'r_frame_rate': None,
            'channels': None,
            'channel_layout': None,
        },
    ],
    'format': {'duration': '0', 'format_name': 'png'},
}


def _make_asset(
    kind: str = LibraryAssetKind.MUSIC,
    name: str = 'Track',
) -> LibraryAsset:
    file = SimpleUploadedFile('file.mp3', b'data', content_type='audio/mpeg')
    return LibraryAsset.objects.create(kind=kind, name=name, file=file)


@pytest.mark.django_db
def test_ingest_music_stores_meta_and_loudness() -> None:
    asset = _make_asset(LibraryAssetKind.MUSIC)
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=_AUDIO_PROBE),
        patch('server.apps.assets.tasks._run_loudness', return_value=-16.3),
    ):
        ingest_library_asset.original_func(str(asset.id))

    asset.refresh_from_db()
    assert asset.meta['format'] == 'mp3'
    assert asset.meta['integrated_loudness_lufs'] == -16.3


@pytest.mark.django_db
def test_ingest_sfx_stores_loudness() -> None:
    asset = _make_asset(LibraryAssetKind.SFX, 'Swoosh')
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=_AUDIO_PROBE),
        patch('server.apps.assets.tasks._run_loudness', return_value=-20.0),
    ):
        ingest_library_asset.original_func(str(asset.id))

    asset.refresh_from_db()
    assert asset.meta['integrated_loudness_lufs'] == -20.0


@pytest.mark.django_db
def test_ingest_loudness_failure_warns_and_continues() -> None:
    asset = _make_asset(LibraryAssetKind.MUSIC)
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=_AUDIO_PROBE),
        patch(
            'server.apps.assets.tasks._run_loudness',
            side_effect=ValueError('parse error'),
        ),
    ):
        ingest_library_asset.original_func(str(asset.id))

    asset.refresh_from_db()
    assert 'integrated_loudness_lufs' not in asset.meta


@pytest.mark.django_db
def test_ingest_watermark_valid_png_with_alpha() -> None:
    asset = _make_asset(LibraryAssetKind.WATERMARK, 'Logo')
    with (
        patch(
            'server.apps.assets.tasks._ffprobe',
            return_value=_PNG_ALPHA_PROBE,
        ),
        patch('server.apps.assets.tasks._transcode'),
    ):
        ingest_library_asset.original_func(str(asset.id))

    asset.refresh_from_db()
    assert asset.meta['format'] == 'png'


@pytest.mark.django_db
def test_ingest_watermark_not_png_raises_fatal() -> None:
    asset = _make_asset(LibraryAssetKind.WATERMARK, 'Logo')
    probe = {
        'streams': [
            {
                'codec_type': 'video',
                'codec_name': 'jpeg',
                'pix_fmt': 'yuvj420p',
                'width': 200,
                'height': 200,
                'r_frame_rate': None,
                'channels': None,
                'channel_layout': None,
            },
        ],
        'format': {'duration': '0', 'format_name': 'jpeg'},
    }
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=probe),
        pytest.raises(FatalProviderError, match='must be a PNG'),
    ):
        ingest_library_asset.original_func(str(asset.id))


@pytest.mark.django_db
def test_ingest_watermark_no_alpha_raises_fatal() -> None:
    asset = _make_asset(LibraryAssetKind.WATERMARK, 'Logo')
    probe = {
        'streams': [
            {
                'codec_type': 'video',
                'codec_name': 'png',
                'pix_fmt': 'rgb24',
                'width': 200,
                'height': 200,
                'r_frame_rate': None,
                'channels': None,
                'channel_layout': None,
            },
        ],
        'format': {'duration': '0', 'format_name': 'png'},
    }
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=probe),
        pytest.raises(FatalProviderError, match='alpha channel'),
    ):
        ingest_library_asset.original_func(str(asset.id))


@pytest.mark.django_db
def test_ingest_intro_no_audio_raises_fatal() -> None:
    asset = _make_asset(LibraryAssetKind.INTRO, 'Opener')
    probe = {
        'streams': [
            {
                'codec_type': 'video',
                'codec_name': 'h264',
                'pix_fmt': 'yuv420p',
                'width': 1920,
                'height': 1080,
                'r_frame_rate': '30/1',
                'channels': None,
                'channel_layout': None,
            },
        ],
        'format': {'duration': '5.0', 'format_name': 'mp4'},
    }
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=probe),
        pytest.raises(FatalProviderError, match='audio stream'),
    ):
        ingest_library_asset.original_func(str(asset.id))


@pytest.mark.django_db
def test_ingest_outro_no_audio_raises_fatal() -> None:
    asset = _make_asset(LibraryAssetKind.OUTRO, 'Closer')
    probe = {
        'streams': [
            {
                'codec_type': 'video',
                'codec_name': 'h264',
                'pix_fmt': 'yuv420p',
                'width': 1920,
                'height': 1080,
                'r_frame_rate': '30/1',
                'channels': None,
                'channel_layout': None,
            },
        ],
        'format': {'duration': '5.0', 'format_name': 'mp4'},
    }
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=probe),
        pytest.raises(FatalProviderError, match='audio stream'),
    ):
        ingest_library_asset.original_func(str(asset.id))


@pytest.mark.django_db
def test_ingest_ffprobe_failure_raises_retryable() -> None:
    asset = _make_asset()
    with (
        patch(
            'server.apps.assets.tasks._ffprobe',
            side_effect=subprocess.CalledProcessError(1, 'ffprobe'),
        ),
        pytest.raises(RetryableProviderError),
    ):
        ingest_library_asset.original_func(str(asset.id))


@pytest.mark.django_db
def test_ingest_ffprobe_missing_binary_raises_fatal() -> None:
    asset = _make_asset()
    with (
        patch(
            'server.apps.assets.tasks._ffprobe',
            side_effect=FileNotFoundError('ffprobe'),
        ),
        pytest.raises(FatalProviderError, match='ffprobe not found'),
    ):
        ingest_library_asset.original_func(str(asset.id))


@pytest.mark.django_db
def test_ingest_video_creates_renditions() -> None:
    from server.apps.assets.models import AssetRendition

    asset = _make_asset(LibraryAssetKind.INTRO, 'Intro Clip')
    fake_mp4 = b'\x00' * 16

    def fake_transcode(inp: str, out: str, args: list) -> None:
        pathlib.Path(out).write_bytes(fake_mp4)

    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=_VIDEO_PROBE),
        patch(
            'server.apps.assets.tasks._transcode',
            side_effect=fake_transcode,
        ),
    ):
        ingest_library_asset.original_func(str(asset.id))

    assert AssetRendition.objects.filter(source=asset).count() == 2


@pytest.mark.django_db
def test_ingest_video_rendition_ffmpeg_failure_logs_and_continues() -> None:
    from server.apps.assets.models import AssetRendition

    asset = _make_asset(LibraryAssetKind.INTRO, 'Intro Clip')
    with (
        patch('server.apps.assets.tasks._ffprobe', return_value=_VIDEO_PROBE),
        patch(
            'server.apps.assets.tasks._transcode',
            side_effect=subprocess.CalledProcessError(1, 'ffmpeg'),
        ),
    ):
        ingest_library_asset.original_func(str(asset.id))

    assert AssetRendition.objects.filter(source=asset).count() == 0


def test_handle_library_asset_ingested_enqueues_task() -> None:
    with patch('server.apps.assets.tasks.kiq_task') as mock_kiq:
        handle_library_asset_ingested(LibraryAssetIngested(asset_id='abc-123'))
        mock_kiq.assert_called_once_with(ingest_library_asset, 'abc-123')


def test_ffprobe_calls_subprocess_and_parses_json() -> None:
    import json

    mock_result = MagicMock()
    mock_result.stdout = json.dumps({'streams': [], 'format': {}})
    with patch('subprocess.run', return_value=mock_result):
        result = _ffprobe('/tmp/test.mp4')
    assert result == {'streams': [], 'format': {}}


def test_run_loudness_parses_integrated_lufs() -> None:
    mock_result = MagicMock()
    mock_result.stderr = 'ignored\n  I:         -16.3 LUFS\n'
    with patch('subprocess.run', return_value=mock_result):
        result = _run_loudness('/tmp/test.mp3')
    assert result == -16.3


def test_run_loudness_raises_on_missing_output() -> None:
    mock_result = MagicMock()
    mock_result.stderr = 'no loudness here'
    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(ValueError, match='Could not parse'):
            _run_loudness('/tmp/test.mp3')


def test_transcode_calls_ffmpeg_with_args() -> None:
    with patch('subprocess.run') as mock_run:
        _transcode('/tmp/in.mp4', '/tmp/out.mp4', ['-vf', 'scale=1920:1080'])
    mock_run.assert_called_once()
