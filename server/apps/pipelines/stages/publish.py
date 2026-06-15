"""Publish stage — uploads final video and thumbnail to YouTube."""

from __future__ import annotations

from datetime import datetime
from typing import Any, override

import httpx

from server.apps.assets.models import Asset
from server.apps.channels.models import YouTubeCredential
from server.apps.generation.clients import youtube as yt_client
from server.apps.pipelines.stages.base import Stage, StageContext, register_stage
from server.apps.publishing.models import PublishJob, PublishStatus


async def _download_asset(asset: Any) -> bytes:
    """Download asset bytes via its presigned URL."""
    url: str = asset.file.url
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


@register_stage
class PublishStage(Stage):
    """Stage: upload final video to YouTube and update the PublishJob record."""

    key = 'publish'
    queue = 'api'
    max_retries = 2
    timeout_s = 1800

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Upload the assembled video to YouTube and record the publish job."""
        meta = ctx.upstream['metadata']
        gate = ctx.upstream.get('review_gate', {})
        final_asset_id: str = ctx.upstream['assembly']['asset_id']
        thumbnail_asset_id: str | None = gate.get('thumbnail_asset_id')
        schedule_at_str: str | None = gate.get('schedule_at')

        schedule_at: datetime | None = None
        if schedule_at_str:
            schedule_at = datetime.fromisoformat(schedule_at_str)

        credential = await YouTubeCredential.objects.aget(channel=ctx.channel)
        access_token = await yt_client.refresh_token_if_needed(credential)

        final_asset = await Asset.objects.aget(id=final_asset_id)
        video_bytes = await _download_asset(final_asset)

        job = await PublishJob.objects.acreate(
            run=ctx.run,
            channel=ctx.channel,
            status=PublishStatus.UPLOADING,
            schedule_at=schedule_at,
            metadata_snapshot={
                'title': meta['title'],
                'description': meta['description'],
                'tags': meta.get('tags', []),
                'category': meta.get('category', 'Education'),
            },
        )

        youtube_video_id = await yt_client.upload_video(
            access_token=access_token,
            video_bytes=video_bytes,
            title=meta['title'],
            description=meta['description'],
            tags=meta.get('tags', []),
            schedule_at=schedule_at,
        )

        if thumbnail_asset_id:
            thumb_asset = await Asset.objects.aget(id=thumbnail_asset_id)
            thumbnail_bytes = await _download_asset(thumb_asset)
            await yt_client.set_thumbnail(
                access_token, youtube_video_id, thumbnail_bytes
            )

        job.youtube_video_id = youtube_video_id
        job.status = PublishStatus.COMPLETED
        await job.asave(update_fields=['youtube_video_id', 'status'])

        return {
            'youtube_video_id': youtube_video_id,
            'publish_job_id': str(job.id),
        }
