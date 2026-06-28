"""ClipsService — all read/write operations for the clips app."""

import asyncio
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, final

import attrs
import django.utils.timezone as tz

from server.apps.clips.logic.constants import CandidateStatus, PostStatus, RenderMode
from server.apps.clips.logic.value_objects import (
    ApproveAllResultPayload,
    ClipCandidateListPayload,
    ClipCandidatePatchPayload,
    ClipCandidatePayload,
    ClipLayoutConfigPatchPayload,
    ClipLayoutConfigPayload,
    ClipOverlayListPayload,
    ClipPostCreatePayload,
    ClipPostListPayload,
    ClipPostPatchPayload,
    ClipPostPayload,
    ClipPreviewStatusPayload,
    ClipRenderPayload,
    ClipSourceFramePayload,
    ClipStyleConfigPatchPayload,
    ClipStyleConfigPayload,
    ClipTimedOverlayCreatePayload,
    ClipTimedOverlayPatchPayload,
    ClipTimedOverlayPayload,
    GateApprovalResultPayload,
)
from server.apps.clips.selectors import (
    get_candidate_source_dimensions,
    get_run_source_asset_id,
)
from server.common.pagination import paginate_queryset
from server.common.storage import PresignUrlHelper

if TYPE_CHECKING:
    from server.apps.clips.models import (
        ClipCandidate,
        ClipLayoutConfig,
        ClipPost,
        ClipStyleConfig,
        ClipTimedOverlay,
    )


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return tz.make_aware(parsed)
    return parsed


def _apply_patch_fields(
    instance: object,
    payload: object,
    field_names: tuple[str, ...],
) -> list[str]:
    """Apply non-None patch fields; return updated field names."""
    update_fields: list[str] = []
    for name in field_names:
        value = getattr(payload, name)
        if value is not None:
            setattr(instance, name, value)
            update_fields.append(name)
    return update_fields


def _config_version(candidate_id: str) -> int:
    """Return a monotonic-ish version from candidate + config timestamps."""
    from server.apps.clips.models import (  # noqa: PLC0415
        ClipCandidate,
        ClipLayoutConfig,
        ClipStyleConfig,
    )

    candidate = ClipCandidate.objects.get(id=candidate_id)
    version = int(candidate.updated_at.timestamp())
    try:
        layout = ClipLayoutConfig.objects.get(candidate_id=candidate_id)
        version += int(layout.updated_at.timestamp())
    except ClipLayoutConfig.DoesNotExist:
        pass
    try:
        style = ClipStyleConfig.objects.get(candidate_id=candidate_id)
        version += int(style.updated_at.timestamp())
    except ClipStyleConfig.DoesNotExist:
        pass
    return version


def _to_candidate_payload(candidate: 'ClipCandidate') -> ClipCandidatePayload:
    channel_id = str(candidate.run.channel_id)
    return ClipCandidatePayload(
        id=str(candidate.id),
        run_id=str(candidate.run_id),
        channel_id=channel_id,
        title=candidate.title,
        hook_text=candidate.hook_text,
        caption_template=candidate.caption_template,
        start_sec=candidate.start_sec,
        end_sec=candidate.end_sec,
        duration_sec=candidate.duration_sec,
        relevance_score=candidate.relevance_score,
        status=candidate.status,
        reason=candidate.reason,
        transcript_excerpt=candidate.transcript_excerpt,
        rejection_reason=candidate.rejection_reason,
        render_asset_id=(
            str(candidate.render_asset_id)
            if candidate.render_asset_id is not None
            else None
        ),
        is_manual=candidate.is_manual,
    )


def _to_layout_payload(
    config: 'ClipLayoutConfig',
    *,
    source_width: int | None = None,
    source_height: int | None = None,
) -> ClipLayoutConfigPayload:
    return ClipLayoutConfigPayload(
        id=str(config.id),
        candidate_id=str(config.candidate_id),
        render_mode=config.render_mode,
        render_format=config.render_format,
        source_width=source_width,
        source_height=source_height,
        manual_crop_x=config.manual_crop_x,
        manual_crop_y=config.manual_crop_y,
        manual_crop_w=config.manual_crop_w,
        manual_crop_h=config.manual_crop_h,
        region_a_x=config.region_a_x,
        region_a_y=config.region_a_y,
        region_a_w=config.region_a_w,
        region_a_h=config.region_a_h,
        region_b_x=config.region_b_x,
        region_b_y=config.region_b_y,
        region_b_w=config.region_b_w,
        region_b_h=config.region_b_h,
        stack_ratio=config.stack_ratio,
        face_detected=config.face_detected,
        detection_confidence=config.detection_confidence,
    )


def _to_style_payload(config: 'ClipStyleConfig') -> ClipStyleConfigPayload:
    return ClipStyleConfigPayload(
        id=str(config.id),
        candidate_id=str(config.candidate_id),
        caption_enabled=config.caption_enabled,
        caption_style=config.caption_style,
        caption_font=config.caption_font,
        caption_size=config.caption_size,
        caption_color=config.caption_color,
        caption_stroke_color=config.caption_stroke_color,
        caption_stroke_width=config.caption_stroke_width,
        caption_bg_color=config.caption_bg_color,
        caption_position=config.caption_position,
        caption_animation=config.caption_animation,
        caption_language=config.caption_language,
        caption_translate_to=config.caption_translate_to,
        emoji_keyword_map=dict(config.emoji_keyword_map),
        hook_enabled=config.hook_enabled,
        hook_style=config.hook_style,
        hook_duration_sec=config.hook_duration_sec,
        hook_font=config.hook_font,
        hook_size=config.hook_size,
        hook_color=config.hook_color,
        hook_bg_color=config.hook_bg_color,
        intro_transition=config.intro_transition,
        outro_transition=config.outro_transition,
        watermark_enabled=config.watermark_enabled,
        watermark_type=config.watermark_type,
        watermark_text=config.watermark_text,
        watermark_image_id=(
            str(config.watermark_image_id)
            if config.watermark_image_id is not None
            else None
        ),
        watermark_position=config.watermark_position,
        watermark_opacity=config.watermark_opacity,
        watermark_size=config.watermark_size,
        progress_bar_enabled=config.progress_bar_enabled,
        progress_bar_position=config.progress_bar_position,
        progress_bar_color=config.progress_bar_color,
        progress_bar_height=config.progress_bar_height,
        intro_asset_id=(
            str(config.intro_asset_id)
            if config.intro_asset_id is not None
            else None
        ),
        outro_asset_id=(
            str(config.outro_asset_id)
            if config.outro_asset_id is not None
            else None
        ),
        music_enabled=config.music_enabled,
        music_asset_id=(
            str(config.music_asset_id)
            if config.music_asset_id is not None
            else None
        ),
        music_volume_db=config.music_volume_db,
        music_fade_in_sec=config.music_fade_in_sec,
        music_fade_out_sec=config.music_fade_out_sec,
    )


def _to_overlay_payload(overlay: 'ClipTimedOverlay') -> ClipTimedOverlayPayload:
    return ClipTimedOverlayPayload(
        id=str(overlay.id),
        candidate_id=str(overlay.candidate_id),
        overlay_type=overlay.overlay_type,
        text=overlay.text,
        image_asset_id=(
            str(overlay.image_asset_id)
            if overlay.image_asset_id is not None
            else None
        ),
        start_sec=overlay.start_sec,
        end_sec=overlay.end_sec,
        x=overlay.x,
        y=overlay.y,
        font_size=overlay.font_size,
        color=overlay.color,
        opacity=overlay.opacity,
    )


def _distribution_status(post: 'ClipPost') -> str:
    if post.status == PostStatus.POSTED and post.platform_url:
        return 'posted'
    if post.status == PostStatus.FAILED:
        return 'failed'
    if post.status == PostStatus.POSTING:
        return 'posting'
    return 'pending_implementation'


def _to_post_payload(post: 'ClipPost') -> ClipPostPayload:
    return ClipPostPayload(
        id=str(post.id),
        candidate_id=str(post.candidate_id),
        platform=post.platform,
        caption=post.caption,
        title=post.title,
        hashtags=list(post.hashtags),
        scheduled_at=_iso(post.scheduled_at),
        posted_at=_iso(post.posted_at),
        status=post.status,
        platform_post_id=post.platform_post_id,
        platform_url=post.platform_url,
        last_error=post.last_error,
        views=post.views,
        likes=post.likes,
        comments=post.comments,
        shares=post.shares,
        revenue_est_usd=str(post.revenue_est_usd),
        distribution_status=_distribution_status(post),
    )


@final
@attrs.define(slots=True, frozen=True)
class ClipsService:
    """Reads and writes all clip domain records."""

    _presign: PresignUrlHelper

    def list_for_run(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipCandidateListPayload:
        """Return paginated candidates for a run."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        qs = ClipCandidate.objects.select_related('run').filter(
            run_id=uuid.UUID(run_id),
        ).order_by(
            '-created_at',
            '-id',
        )
        rows, next_cursor, total = paginate_queryset(
            qs,
            cursor=cursor,
            limit=limit,
        )
        return ClipCandidateListPayload(
            items=[_to_candidate_payload(row) for row in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def approved_for_run(self, run_id: str) -> list[ClipCandidatePayload]:
        """Return only approved candidates for a run."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        return [
            _to_candidate_payload(c)
            for c in ClipCandidate.objects.select_related('run').filter(
                run_id=uuid.UUID(run_id),
                status=CandidateStatus.APPROVED,
            ).order_by('-relevance_score')
        ]

    def get_by_id(self, candidate_id: str) -> ClipCandidatePayload:
        """Return a single candidate by ID."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        return _to_candidate_payload(
            ClipCandidate.objects.select_related('run').get(id=candidate_id),
        )

    def patch(
        self,
        candidate_id: str,
        payload: ClipCandidatePatchPayload,
    ) -> ClipCandidatePayload:
        """Update editable candidate fields."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        update_fields = _apply_patch_fields(
            candidate,
            payload,
            (
                'title',
                'hook_text',
                'start_sec',
                'end_sec',
                'caption_template',
            ),
        )
        if update_fields:
            candidate.save(update_fields=update_fields)
        return _to_candidate_payload(candidate)

    def approve(self, candidate_id: str) -> ClipCandidatePayload:
        """Mark a candidate as APPROVED."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        candidate.status = CandidateStatus.APPROVED
        candidate.save(update_fields=['status'])
        return _to_candidate_payload(candidate)

    def reject(
        self,
        candidate_id: str,
        reason: str = '',
    ) -> ClipCandidatePayload:
        """Mark a candidate as REJECTED with an optional reason."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        candidate.status = CandidateStatus.REJECTED
        candidate.rejection_reason = reason
        candidate.save(update_fields=['status', 'rejection_reason'])
        return _to_candidate_payload(candidate)

    def approve_all(self, run_id: str) -> ApproveAllResultPayload:
        """Approve every PROPOSED candidate on a run."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        qs = ClipCandidate.objects.filter(
            run_id=uuid.UUID(run_id),
            status=CandidateStatus.PROPOSED,
        )
        count = qs.count()
        qs.update(status=CandidateStatus.APPROVED)
        return ApproveAllResultPayload(approved_count=count)

    def sync_gate_candidates(
        self,
        run_id: str,
        approved_candidate_ids: list[str],
    ) -> int:
        """Bulk-update candidate statuses when a clip gate is approved."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        approved_uuids = [uuid.UUID(value) for value in approved_candidate_ids]
        ClipCandidate.objects.filter(
            run_id=uuid.UUID(run_id),
            id__in=approved_uuids,
        ).update(status=CandidateStatus.APPROVED)
        ClipCandidate.objects.filter(
            run_id=uuid.UUID(run_id),
            status=CandidateStatus.PROPOSED,
        ).exclude(id__in=approved_uuids).update(
            status=CandidateStatus.REJECTED,
            rejection_reason='Not selected at gate',
        )
        return len(approved_candidate_ids)

    def approve_gate(
        self,
        run_id: str,
        approved_candidate_ids: list[str],
    ) -> GateApprovalResultPayload:
        """Sync candidates and resume the clip approval gate."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _approve_gate_sync,
            advance_pipeline_impl,
        )

        count = self.sync_gate_candidates(run_id, approved_candidate_ids)
        output: dict[str, Any] = {
            'approved_candidate_ids': approved_candidate_ids,
        }
        _approve_gate_sync(run_id, 'clip_approval_gate', output)
        asyncio.run(advance_pipeline_impl(run_id))
        return GateApprovalResultPayload(
            status='approved',
            approved_count=count,
        )

    def get_layout(self, candidate_id: str) -> ClipLayoutConfigPayload:
        """Return layout config for a candidate."""
        from server.apps.clips.models import ClipLayoutConfig  # noqa: PLC0415

        config = ClipLayoutConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        source_w, source_h = get_candidate_source_dimensions(candidate_id)
        return _to_layout_payload(
            config,
            source_width=source_w,
            source_height=source_h,
        )

    def patch_layout(
        self,
        candidate_id: str,
        payload: ClipLayoutConfigPatchPayload,
    ) -> ClipLayoutConfigPayload:
        """Update layout config fields."""
        from server.apps.clips.models import ClipLayoutConfig  # noqa: PLC0415

        config = ClipLayoutConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        update_fields = _apply_patch_fields(
            config,
            payload,
            (
                'render_mode',
                'render_format',
                'manual_crop_x',
                'manual_crop_y',
                'manual_crop_w',
                'manual_crop_h',
                'region_a_x',
                'region_a_y',
                'region_a_w',
                'region_a_h',
                'region_b_x',
                'region_b_y',
                'region_b_w',
                'region_b_h',
                'stack_ratio',
            ),
        )
        if update_fields:
            config.save(update_fields=update_fields)
        source_w, source_h = get_candidate_source_dimensions(candidate_id)
        return _to_layout_payload(
            config,
            source_width=source_w,
            source_height=source_h,
        )

    def reset_smart_crop(self, candidate_id: str) -> ClipLayoutConfigPayload:
        """Clear manual crop and re-run speaker-aware smart crop detection."""
        import tempfile
        from pathlib import Path

        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipLayoutConfig,
        )
        from server.apps.rendering.speaker_detection import (  # noqa: PLC0415
            SpeakerDetectionService,
        )

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        config = ClipLayoutConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        config.render_mode = RenderMode.SMART_CROP
        config.manual_crop_x = None
        config.manual_crop_y = None
        config.manual_crop_w = None
        config.manual_crop_h = None
        config.face_detected = None
        config.detection_confidence = None

        asset_id = get_run_source_asset_id(str(candidate.run_id))
        update_fields = [
            'render_mode',
            'manual_crop_x',
            'manual_crop_y',
            'manual_crop_w',
            'manual_crop_h',
            'face_detected',
            'detection_confidence',
        ]
        if asset_id is not None:
            asset = Asset.objects.get(id=uuid.UUID(asset_id))
            with tempfile.NamedTemporaryFile(
                suffix='.mp4',
                delete=False,
            ) as tmp:
                tmp_path = tmp.name
            try:
                with asset.file.open('rb') as fh:
                    Path(tmp_path).write_bytes(fh.read())
                result = SpeakerDetectionService().detect(
                    video_path=Path(tmp_path),
                    start_sec=candidate.start_sec,
                    end_sec=candidate.end_sec,
                )
                config.manual_crop_x = result.crop_x
                config.manual_crop_y = 0
                config.manual_crop_w = result.crop_w
                config.manual_crop_h = result.crop_h
                config.face_detected = result.face_detected
                config.detection_confidence = result.confidence
                update_fields.extend(
                    [
                        'manual_crop_x',
                        'manual_crop_y',
                        'manual_crop_w',
                        'manual_crop_h',
                        'face_detected',
                        'detection_confidence',
                    ],
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        config.save(update_fields=update_fields)
        source_w, source_h = get_candidate_source_dimensions(candidate_id)
        return _to_layout_payload(
            config,
            source_width=source_w,
            source_height=source_h,
        )

    def get_style(self, candidate_id: str) -> ClipStyleConfigPayload:
        """Return style config for a candidate."""
        from server.apps.clips.models import ClipStyleConfig  # noqa: PLC0415

        config = ClipStyleConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        return _to_style_payload(config)

    def patch_style(
        self,
        candidate_id: str,
        payload: ClipStyleConfigPatchPayload,
    ) -> ClipStyleConfigPayload:
        """Update style config fields."""
        from server.apps.clips.models import ClipStyleConfig  # noqa: PLC0415

        config = ClipStyleConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        update_fields = _apply_patch_fields(
            config,
            payload,
            (
                'caption_enabled',
                'caption_style',
                'caption_font',
                'caption_size',
                'caption_color',
                'caption_stroke_color',
                'caption_stroke_width',
                'caption_bg_color',
                'caption_position',
                'caption_animation',
                'caption_language',
                'caption_translate_to',
                'hook_enabled',
                'hook_style',
                'hook_duration_sec',
                'hook_font',
                'hook_size',
                'hook_color',
                'hook_bg_color',
                'intro_transition',
                'outro_transition',
                'watermark_enabled',
                'watermark_type',
                'watermark_text',
                'watermark_position',
                'watermark_opacity',
                'watermark_size',
                'progress_bar_enabled',
                'progress_bar_position',
                'progress_bar_color',
                'progress_bar_height',
                'music_enabled',
                'music_volume_db',
                'music_fade_in_sec',
                'music_fade_out_sec',
            ),
        )
        fk_map = {
            'watermark_image_id': payload.watermark_image_id,
            'intro_asset_id': payload.intro_asset_id,
            'outro_asset_id': payload.outro_asset_id,
            'music_asset_id': payload.music_asset_id,
        }
        for field_name, value in fk_map.items():
            if value is not None:
                setattr(
                    config,
                    field_name,
                    uuid.UUID(value) if value else None,
                )
                update_fields.append(field_name)
        if payload.emoji_keyword_map is not None:
            config.emoji_keyword_map = dict(payload.emoji_keyword_map)
            update_fields.append('emoji_keyword_map')
        if update_fields:
            config.save(update_fields=update_fields)
        return _to_style_payload(config)

    def list_overlays(
        self,
        candidate_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipOverlayListPayload:
        """Return paginated timed overlays for a candidate."""
        from server.apps.clips.models import ClipTimedOverlay  # noqa: PLC0415

        qs = ClipTimedOverlay.objects.filter(  # type: ignore[misc]
            candidate_id=candidate_id,
        ).order_by('-created_at', '-id')
        rows, next_cursor, total = paginate_queryset(
            qs,
            cursor=cursor,
            limit=limit,
        )
        return ClipOverlayListPayload(
            items=[_to_overlay_payload(row) for row in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def create_overlay(
        self,
        candidate_id: str,
        payload: ClipTimedOverlayCreatePayload,
    ) -> ClipTimedOverlayPayload:
        """Create a timed overlay on a candidate."""
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipTimedOverlay,
        )

        ClipCandidate.objects.get(id=candidate_id)
        overlay = ClipTimedOverlay.objects.create(
            candidate_id=candidate_id,
            overlay_type=payload.overlay_type,
            text=payload.text,
            image_asset_id=(
                uuid.UUID(payload.image_asset_id)
                if payload.image_asset_id
                else None
            ),
            start_sec=payload.start_sec,
            end_sec=payload.end_sec,
            x=payload.x,
            y=payload.y,
            font_size=payload.font_size,
            color=payload.color,
            opacity=payload.opacity,
        )
        return _to_overlay_payload(overlay)

    def get_overlay(
        self,
        candidate_id: str,
        overlay_id: str,
    ) -> ClipTimedOverlayPayload:
        """Return one timed overlay."""
        from server.apps.clips.models import ClipTimedOverlay  # noqa: PLC0415

        overlay = ClipTimedOverlay.objects.get(  # type: ignore[misc]
            id=overlay_id,
            candidate_id=candidate_id,
        )
        return _to_overlay_payload(overlay)

    def patch_overlay(
        self,
        candidate_id: str,
        overlay_id: str,
        payload: ClipTimedOverlayPatchPayload,
    ) -> ClipTimedOverlayPayload:
        """Update a timed overlay."""
        from server.apps.clips.models import ClipTimedOverlay  # noqa: PLC0415

        overlay = ClipTimedOverlay.objects.get(  # type: ignore[misc]
            id=overlay_id,
            candidate_id=candidate_id,
        )
        update_fields = _apply_patch_fields(
            overlay,
            payload,
            (
                'overlay_type',
                'text',
                'start_sec',
                'end_sec',
                'x',
                'y',
                'font_size',
                'color',
                'opacity',
            ),
        )
        if payload.image_asset_id is not None:
            overlay.image_asset_id = (
                uuid.UUID(payload.image_asset_id)
                if payload.image_asset_id
                else None
            )
            update_fields.append('image_asset_id')
        if update_fields:
            overlay.save(update_fields=update_fields)
        return _to_overlay_payload(overlay)

    def delete_overlay(self, candidate_id: str, overlay_id: str) -> None:
        """Delete a timed overlay."""
        from server.apps.clips.models import ClipTimedOverlay  # noqa: PLC0415

        ClipTimedOverlay.objects.filter(  # type: ignore[misc]
            id=overlay_id,
            candidate_id=candidate_id,
        ).delete()

    def list_posts(
        self,
        candidate_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipPostListPayload:
        """Return paginated distribution posts."""
        from server.apps.clips.models import ClipPost  # noqa: PLC0415

        qs = ClipPost.objects.filter(candidate_id=candidate_id).order_by(  # type: ignore[misc]
            '-created_at',
            '-id',
        )
        rows, next_cursor, total = paginate_queryset(
            qs,
            cursor=cursor,
            limit=limit,
        )
        return ClipPostListPayload(
            items=[_to_post_payload(row) for row in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def get_render(self, candidate_id: str) -> ClipRenderPayload:
        """Return presigned URL for the candidate render asset."""
        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.get(id=candidate_id)
        if candidate.render_asset_id is None:
            return ClipRenderPayload(
                candidate_id=candidate_id,
                asset_id=None,
                url=None,
            )
        asset = Asset.objects.get(id=candidate.render_asset_id)
        return ClipRenderPayload(
            candidate_id=candidate_id,
            asset_id=str(asset.id),
            url=self._presign.presign_get(asset.file.name or ''),
        )

    def trigger_preview(
        self,
        candidate_id: str,
        *,
        force: bool = False,
    ) -> ClipPreviewStatusPayload:
        """Queue a lightweight preview render for one candidate."""
        from django.core.cache import cache  # noqa: PLC0415

        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        ClipCandidate.objects.get(id=candidate_id)
        cache_key = f'clip_preview:{candidate_id}'
        if force:
            cache.delete(cache_key)
        cache.set(
            cache_key,
            {'status': 'queued'},
            timeout=3600,
        )
        return ClipPreviewStatusPayload(
            candidate_id=candidate_id,
            status='queued',
            url=None,
            config_version=_config_version(candidate_id),
        )

    def get_preview_status(
        self,
        candidate_id: str,
    ) -> ClipPreviewStatusPayload:
        """Return preview job state for one candidate."""
        from django.core.cache import cache  # noqa: PLC0415

        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        version = _config_version(candidate_id)
        candidate = ClipCandidate.objects.get(id=candidate_id)
        cached = cache.get(f'clip_preview:{candidate_id}')
        if isinstance(cached, dict) and cached.get('status') == 'queued':
            return ClipPreviewStatusPayload(
                candidate_id=candidate_id,
                status='queued',
                url=None,
                config_version=version,
            )
        if candidate.render_asset_id is not None:
            asset = Asset.objects.get(id=candidate.render_asset_id)
            return ClipPreviewStatusPayload(
                candidate_id=candidate_id,
                status='ready',
                url=self._presign.presign_get(asset.file.name or ''),
                config_version=version,
            )
        return ClipPreviewStatusPayload(
            candidate_id=candidate_id,
            status='idle',
            url=None,
            config_version=version,
        )

    def get_source_frame(
        self,
        candidate_id: str,
        time_sec: float,
    ) -> ClipSourceFramePayload:
        """Extract a JPEG frame from the source video at the given time."""
        import hashlib
        import subprocess  # noqa: S404
        import tempfile
        from pathlib import Path

        from django.core.files.base import ContentFile  # noqa: PLC0415

        from server.apps.assets.models import Asset, AssetKind  # noqa: PLC0415
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        clamped = max(
            candidate.start_sec,
            min(time_sec, candidate.end_sec),
        )
        asset_id = get_run_source_asset_id(str(candidate.run_id))
        if asset_id is None:
            msg = 'Source video not available for this candidate'
            raise ValueError(msg)

        source_asset = Asset.objects.get(id=uuid.UUID(asset_id))
        source_w, source_h = get_candidate_source_dimensions(candidate_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / 'source.mp4'
            frame_path = Path(tmpdir) / 'frame.jpg'
            with source_asset.file.open('rb') as fh:
                video_path.write_bytes(fh.read())
            cmd = [
                'ffmpeg',
                '-y',
                '-ss',
                f'{clamped:.3f}',
                '-i',
                str(video_path),
                '-frames:v',
                '1',
                '-q:v',
                '2',
                str(frame_path),
            ]
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                msg = f'Frame extraction failed: {result.stderr[:200]}'
                raise RuntimeError(msg)
            frame_bytes = frame_path.read_bytes()

        checksum = hashlib.sha256(frame_bytes).hexdigest()
        thumb = Asset(
            kind=AssetKind.THUMBNAIL,
            mime='image/jpeg',
            checksum=checksum,
            run=candidate.run,
        )
        thumb.file.save(
            f'source_frame_{candidate_id}_{int(clamped)}.jpg',
            ContentFile(frame_bytes),
            save=False,
        )
        thumb.save()
        return ClipSourceFramePayload(
            candidate_id=candidate_id,
            time_sec=clamped,
            url=self._presign.presign_get(thumb.file.name or ''),
            width=source_w,
            height=source_h,
        )

    def create_post(
        self,
        candidate_id: str,
        payload: ClipPostCreatePayload,
    ) -> ClipPostPayload:
        """Create a distribution post."""
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipPost,
        )

        ClipCandidate.objects.get(id=candidate_id)
        post = ClipPost.objects.create(
            candidate_id=candidate_id,
            platform=payload.platform,
            caption=payload.caption,
            title=payload.title,
            hashtags=payload.hashtags or [],
            scheduled_at=_parse_dt(payload.scheduled_at),
        )
        return _to_post_payload(post)

    def get_post(self, candidate_id: str, post_id: str) -> ClipPostPayload:
        """Return one distribution post."""
        from server.apps.clips.models import ClipPost  # noqa: PLC0415

        post = ClipPost.objects.get(id=post_id, candidate_id=candidate_id)  # type: ignore[misc]
        return _to_post_payload(post)

    def patch_post(
        self,
        candidate_id: str,
        post_id: str,
        payload: ClipPostPatchPayload,
    ) -> ClipPostPayload:
        """Update a distribution post."""
        from server.apps.clips.models import ClipPost  # noqa: PLC0415

        post = ClipPost.objects.get(id=post_id, candidate_id=candidate_id)  # type: ignore[misc]
        update_fields = _apply_patch_fields(
            post,
            payload,
            ('platform', 'caption', 'title', 'status'),
        )
        if payload.hashtags is not None:
            post.hashtags = payload.hashtags
            update_fields.append('hashtags')
        if payload.scheduled_at is not None:
            post.scheduled_at = _parse_dt(payload.scheduled_at)
            update_fields.append('scheduled_at')
        if update_fields:
            post.save(update_fields=update_fields)
        return _to_post_payload(post)


ClipCandidateService = ClipsService
