"""ClipIngest stage — download source video and persist as VIDEO_SEGMENT."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


def _download_with_ytdlp(url: str, out_path: str) -> dict[str, Any]:
    """Download via yt-dlp; returns {'title', 'duration_sec'}."""
    import yt_dlp  # noqa: PLC0415

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': out_path,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return {
        'title': info.get('title', ''),
        'duration_sec': float(info.get('duration', 0)),
    }


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

        source_url: str = ctx.run.topic
        prompt = ctx.run.prompt_snapshot

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / 'source.mp4')

            if source_url.startswith('http'):
                info = await asyncio.to_thread(
                    _download_with_ytdlp,
                    source_url,
                    out_path,
                )
                title: str = info['title']
                duration_sec: float = info['duration_sec']
            else:
                from server.apps.assets.models import (  # noqa: PLC0415
                    LibraryAsset,
                )

                lib_asset = await LibraryAsset.objects.aget(id=source_url)
                video_bytes = await asyncio.to_thread(lib_asset.file.read)
                await asyncio.to_thread(Path(out_path).write_bytes, video_bytes)
                title = prompt.get('source_title', 'Uploaded Video')
                duration_sec = 0.0

            video_bytes = await asyncio.to_thread(Path(out_path).read_bytes)

        asset = await ctx.assets.save(
            kind=AssetKind.VIDEO_SEGMENT,
            content=video_bytes,
            filename='source.mp4',
            mime='video/mp4',
        )
        return {
            'asset_id': str(asset.id),
            'source_title': title,
            'source_duration_sec': duration_sec,
            'source_url': source_url,
        }
