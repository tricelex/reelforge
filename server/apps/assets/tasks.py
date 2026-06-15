"""Background tasks for the assets app."""

import json
import subprocess  # noqa: S404
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import async_to_sync

from server.apps.assets.logic.events import LibraryAssetIngested
from server.common.broker import broker

if TYPE_CHECKING:
    from server.apps.assets.models import (
        LibraryAsset,
    )

logger = structlog.get_logger(__name__)

_RENDITION_PROFILES: dict[str, list[str]] = {
    '1080p30_h264': [
        '-vf',
        'scale=1920:1080',
        '-r',
        '30',
        '-c:v',
        'libx264',
        '-c:a',
        'aac',
    ],
    '9x16_1080': [
        '-vf',
        'scale=1080:1920',
        '-r',
        '30',
        '-c:v',
        'libx264',
        '-c:a',
        'aac',
    ],
}


def _ffprobe(path: str) -> dict[str, Any]:
    """Run ffprobe and return JSON stream/format info."""
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_streams',
            '-show_format',
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def _run_loudness(path: str) -> float:
    """Return EBU R128 integrated loudness in LUFS."""
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            'ffmpeg',
            '-i',
            path,
            '-filter_complex',
            'ebur128=framelog=verbose',
            '-f',
            'null',
            '-',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stderr.splitlines():
        if 'I:' in line and 'LUFS' in line:
            return float(line.split('I:')[1].split('LUFS')[0].strip())
    raise ValueError(f'Could not parse loudness from ffmpeg output for {path}')


def _transcode(
    input_path: str,
    output_path: str,
    extra_args: list[str],
) -> None:
    """Transcode input to output using ffmpeg with the given extra arguments."""
    subprocess.run(  # noqa: S603
        ['ffmpeg', '-y', '-i', input_path, *extra_args, output_path],  # noqa: S607
        capture_output=True,
        check=True,
    )


def _validate_kind(
    kind: str,
    video_streams: list[dict[str, Any]],
    audio_streams: list[dict[str, Any]],
) -> None:
    """Raise FatalProviderError if kind-specific validation fails."""
    from server.apps.assets.models import LibraryAssetKind  # noqa: PLC0415
    from server.common.exceptions import FatalProviderError  # noqa: PLC0415

    if kind == LibraryAssetKind.WATERMARK:
        if not video_streams or video_streams[0].get('codec_name') != 'png':
            raise FatalProviderError(
                'Watermark must be a PNG',
                provider='validator',
                error_code='WATERMARK_NOT_PNG',
            )
        if 'yuva' not in (video_streams[0].get('pix_fmt') or ''):
            raise FatalProviderError(
                'Watermark PNG must have alpha channel',
                provider='validator',
                error_code='WATERMARK_NO_ALPHA',
            )

    if (
        kind in {LibraryAssetKind.INTRO, LibraryAssetKind.OUTRO}
        and not audio_streams
    ):
        raise FatalProviderError(
            'Intro/outro must contain an audio stream',
            provider='validator',
            error_code='INTRO_OUTRO_NO_AUDIO',
        )


def _save_rendition(
    asset: 'LibraryAsset',
    profile_name: str,
    out_path: str,
) -> None:
    """Persist a transcoded rendition file to storage."""
    from django.core.files import File  # noqa: PLC0415

    from server.apps.assets.models import AssetRendition  # noqa: PLC0415

    with Path(out_path).open('rb') as fh:
        rendition = AssetRendition(source=asset, profile=profile_name)
        rendition.file.save(f'{uuid.uuid4()}.mp4', File(fh), save=False)
        rendition.save()
    Path(out_path).unlink(missing_ok=True)


def _create_renditions(asset: 'LibraryAsset', tmp_path: str) -> None:
    """Generate all rendition profiles for a video-bearing library asset."""
    for profile_name, ffmpeg_args in _RENDITION_PROFILES.items():
        out_path = str(Path(tmp_path).with_suffix(f'.{profile_name}.mp4'))
        try:
            _transcode(tmp_path, out_path, ffmpeg_args)
        except subprocess.CalledProcessError:
            logger.exception(
                'rendition_failed',
                asset_id=str(asset.id),
                profile=profile_name,
            )
            continue

        if Path(out_path).exists():
            _save_rendition(asset, profile_name, out_path)


@broker.task
def ingest_library_asset(asset_id: str) -> None:
    """Run the upload normalisation pipeline for a LibraryAsset.

    Steps: ffprobe → kind validation → EBU R128 loudness → rendition generation.
    """
    from server.apps.assets.models import (  # noqa: PLC0415
        LibraryAsset,
        LibraryAssetKind,
    )
    from server.common.exceptions import (  # noqa: PLC0415
        RetryableProviderError,
    )

    asset = LibraryAsset.objects.get(id=asset_id)

    file_name = asset.file.name or 'asset.bin'
    suffix = Path(file_name).suffix or '.bin'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        asset.file.open('rb')
        try:
            tmp.write(asset.file.read())
        finally:
            asset.file.close()
        tmp_path = tmp.name

    try:
        try:
            probe = _ffprobe(tmp_path)
        except subprocess.CalledProcessError as exc:
            raise RetryableProviderError(str(exc), provider='ffprobe') from exc

        streams = probe.get('streams', [])
        fmt = probe.get('format', {})
        video_streams = [s for s in streams if s.get('codec_type') == 'video']
        audio_streams = [s for s in streams if s.get('codec_type') == 'audio']

        meta: dict[str, Any] = {
            'duration': float(fmt.get('duration', 0)),
            'format': fmt.get('format_name', ''),
            'streams': [
                {
                    'codec_type': s.get('codec_type'),
                    'codec_name': s.get('codec_name'),
                    'width': s.get('width'),
                    'height': s.get('height'),
                    'r_frame_rate': s.get('r_frame_rate'),
                    'channels': s.get('channels'),
                    'channel_layout': s.get('channel_layout'),
                    'pix_fmt': s.get('pix_fmt'),
                }
                for s in streams
            ],
        }

        _validate_kind(asset.kind, video_streams, audio_streams)

        if asset.kind in {LibraryAssetKind.MUSIC, LibraryAssetKind.SFX}:
            try:
                meta['integrated_loudness_lufs'] = _run_loudness(tmp_path)
            except Exception as exc:
                logger.warning(
                    'loudness_analysis_failed',
                    asset_id=asset_id,
                    error=str(exc),
                )

        if video_streams:
            _create_renditions(asset, tmp_path)

        asset.meta = meta
        asset.save(update_fields=['meta'])

    finally:
        Path(tmp_path).unlink(missing_ok=True)

    logger.info('library_asset_ingested', asset_id=asset_id, kind=asset.kind)


def handle_library_asset_ingested(event: LibraryAssetIngested) -> None:
    """EventBus handler — enqueues the ingest task."""
    async_to_sync(ingest_library_asset.kiq)(event.asset_id)
