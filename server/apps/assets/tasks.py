"""Background tasks for the assets app."""

import json
import subprocess
import tempfile
import uuid
from pathlib import Path

import structlog
from asgiref.sync import async_to_sync

from server.apps.assets.logic.events import LibraryAssetIngested
from server.common.broker import broker

logger = structlog.get_logger(__name__)

_RENDITION_PROFILES: dict[str, list[str]] = {
    '1080p30_h264': ['-vf', 'scale=1920:1080', '-r', '30', '-c:v', 'libx264', '-c:a', 'aac'],
    '9x16_1080': ['-vf', 'scale=1080:1920', '-r', '30', '-c:v', 'libx264', '-c:a', 'aac'],
}


def _ffprobe(path: str) -> dict:
    result = subprocess.run(
        [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
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
    result = subprocess.run(
        ['ffmpeg', '-i', path, '-filter_complex', 'ebur128=framelog=verbose', '-f', 'null', '-'],
        capture_output=True,
        text=True,
    )
    for line in result.stderr.splitlines():
        if 'I:' in line and 'LUFS' in line:
            return float(line.split('I:')[1].split('LUFS')[0].strip())
    raise ValueError(f'Could not parse loudness from ffmpeg output for {path}')


def _transcode(input_path: str, output_path: str, extra_args: list[str]) -> None:
    subprocess.run(
        ['ffmpeg', '-y', '-i', input_path] + extra_args + [output_path],
        capture_output=True,
        check=True,
    )


@broker.task
def ingest_library_asset(asset_id: str) -> None:
    """Run the upload normalisation pipeline for a LibraryAsset.

    Steps: ffprobe → kind validation → EBU R128 loudness → rendition generation.
    """
    from server.apps.assets.models import (  # noqa: PLC0415
        AssetRendition,
        LibraryAsset,
        LibraryAssetKind,
    )
    from server.apps.core.exceptions import (  # noqa: PLC0415
        FatalProviderError,
        RetryableProviderError,
    )

    asset = LibraryAsset.objects.get(id=asset_id)

    suffix = Path(asset.file.name).suffix or '.bin'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        asset.file.open('rb')
        try:
            tmp.write(asset.file.read())
        finally:
            asset.file.close()
        tmp_path = tmp.name

    try:
        # 1. ffprobe
        try:
            probe = _ffprobe(tmp_path)
        except subprocess.CalledProcessError as exc:
            raise RetryableProviderError(
                str(exc), provider='ffprobe'
            ) from exc

        streams = probe.get('streams', [])
        fmt = probe.get('format', {})
        video_streams = [s for s in streams if s.get('codec_type') == 'video']
        audio_streams = [s for s in streams if s.get('codec_type') == 'audio']

        meta: dict = {
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

        # 2. Validation per kind
        kind = asset.kind
        if kind == LibraryAssetKind.WATERMARK:
            if not video_streams or video_streams[0].get('codec_name') != 'png':
                raise FatalProviderError(
                    'Watermark must be a PNG', provider='validator', error_code='WATERMARK_NOT_PNG'
                )
            if 'yuva' not in (video_streams[0].get('pix_fmt') or ''):
                raise FatalProviderError(
                    'Watermark PNG must have alpha channel',
                    provider='validator',
                    error_code='WATERMARK_NO_ALPHA',
                )

        if kind in {LibraryAssetKind.INTRO, LibraryAssetKind.OUTRO}:
            if not audio_streams:
                raise FatalProviderError(
                    'Intro/outro must contain an audio stream',
                    provider='validator',
                    error_code='INTRO_OUTRO_NO_AUDIO',
                )

        # 3. EBU R128 loudness (music / SFX only)
        if kind in {LibraryAssetKind.MUSIC, LibraryAssetKind.SFX}:
            try:
                meta['integrated_loudness_lufs'] = _run_loudness(tmp_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    'loudness_analysis_failed', asset_id=asset_id, error=str(exc)
                )

        # 4. Rendition generation (video-bearing assets only)
        if video_streams:
            for profile_name, ffmpeg_args in _RENDITION_PROFILES.items():
                out_path = str(Path(tmp_path).with_suffix(f'.{profile_name}.mp4'))
                try:
                    _transcode(tmp_path, out_path, ffmpeg_args)
                except subprocess.CalledProcessError:
                    logger.error(
                        'rendition_failed',
                        asset_id=asset_id,
                        profile=profile_name,
                    )
                    continue

                if Path(out_path).exists():
                    from django.core.files import File  # noqa: PLC0415

                    with open(out_path, 'rb') as fh:
                        rendition = AssetRendition(source=asset, profile=profile_name)
                        rendition.file.save(f'{uuid.uuid4()}.mp4', File(fh), save=False)
                        rendition.save()
                    Path(out_path).unlink(missing_ok=True)

        asset.meta = meta
        asset.save(update_fields=['meta'])

    finally:
        Path(tmp_path).unlink(missing_ok=True)

    logger.info('library_asset_ingested', asset_id=asset_id, kind=kind)


def handle_library_asset_ingested(event: LibraryAssetIngested) -> None:
    """EventBus handler — enqueues the ingest task."""
    async_to_sync(ingest_library_asset.kiq)(event.asset_id)
