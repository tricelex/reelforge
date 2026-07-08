"""ClipIngest stage — download source video and persist as VIDEO_SEGMENT."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, override

from server.apps.clips.models import ClipSource
from server.apps.clips.source_services import resolve_ingest_key
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.yt_dlp import build_yt_dlp_opts


def _download_with_ytdlp(url: str, out_path: str) -> dict[str, Any]:
    """Download via yt-dlp; returns {'title', 'duration_sec'}."""
    import yt_dlp  # noqa: PLC0415

    ydl_opts = build_yt_dlp_opts(
        format='bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        outtmpl=out_path,
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return {
        'title': info.get('title', ''),
        'duration_sec': float(info.get('duration', 0)),
    }


async def _resolve_ingest_input(
    ctx: StageContext,
) -> tuple[str, str]:
    """Return ingest key and display title for the run source."""
    prompt = ctx.run.prompt_snapshot
    clip_source = await ClipSource.objects.filter(run_id=ctx.run.id).afirst()
    if clip_source is not None:
        ingest_key = resolve_ingest_key(clip_source)
        default_title = prompt.get('source_title', 'Uploaded Video')
        title = clip_source.title or default_title
        return ingest_key, str(title)

    source_url: str = ctx.run.topic
    if source_url.startswith('http'):
        title = str(prompt.get('source_title', source_url))
    else:
        title = str(prompt.get('source_title', 'Uploaded Video'))
    return source_url, title


@register_stage
class ClipIngestStage(Stage):
    """Stage 1: download source video → Asset(VIDEO_SEGMENT)."""

    key = 'clip_ingest'
    queue = 'render'
    max_retries = 3
    timeout_s = 1800

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Download or copy source video and persist as VIDEO_SEGMENT asset."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415

        source_url, display_title = await _resolve_ingest_input(ctx)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / 'source.mp4')

            if source_url.startswith('http'):
                info = await asyncio.to_thread(
                    _download_with_ytdlp,
                    source_url,
                    out_path,
                )
                title: str = info['title'] or display_title
                duration_sec: float = info['duration_sec']
            else:
                from server.apps.assets.models import (  # noqa: PLC0415
                    LibraryAsset,
                )

                lib_asset = await LibraryAsset.objects.aget(id=source_url)
                video_bytes = await asyncio.to_thread(lib_asset.file.read)
                await asyncio.to_thread(Path(out_path).write_bytes, video_bytes)
                title = display_title or 'Uploaded Video'
                duration_sec = 0.0

            video_bytes = await asyncio.to_thread(Path(out_path).read_bytes)

        from server.apps.clips.selectors import (
            dimensions_from_probe,
        )
        from server.apps.rendering.ffmpeg import async_ffprobe  # noqa: PLC0415

        width: int | None = None
        height: int | None = None
        try:
            probe = await async_ffprobe(out_path)
            width, height = dimensions_from_probe(probe)
        except RuntimeError:
            pass

        asset = await ctx.assets.save(
            kind=AssetKind.VIDEO_SEGMENT,
            content=video_bytes,
            filename='source.mp4',
            mime='video/mp4',
        )
        if width is not None and height is not None:
            meta = dict(asset.meta)
            meta['width'] = width
            meta['height'] = height
            asset.meta = meta
            await asset.asave(update_fields=['meta'])

        output: dict[str, Any] = {
            'asset_id': str(asset.id),
            'source_title': title,
            'source_duration_sec': duration_sec,
            'source_url': source_url,
        }
        if width is not None:
            output['source_width'] = width
        if height is not None:
            output['source_height'] = height
        return output
