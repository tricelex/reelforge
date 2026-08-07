"""ClipsService — all read/write operations for the clips app."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, final

import attrs
import django.utils.timezone as tz
from django.core.cache import BaseCache
from django.core.exceptions import ValidationError

from server.apps.clips.logic.composition import (
    fit_mode_from_composition,
    normalize_background_color,
    normalize_background_mode,
    normalize_blur_strength,
    normalize_foreground_treatment,
    resolve_composition,
)
from server.apps.clips.logic.constants import (
    CandidateStatus,
    FitMode,
    PostStatus,
    RenderMode,
    render_format_dimensions,
)
from server.apps.clips.logic.value_objects import (
    ApproveAllResultPayload,
    CaptionPresetListPayload,
    CaptionPresetPayload,
    ClipBeatPayload,
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
    ClipSfxListPayload,
    ClipSourceFramePayload,
    ClipStyleConfigPatchPayload,
    ClipStyleConfigPayload,
    ClipTimedOverlayCreatePayload,
    ClipTimedOverlayPatchPayload,
    ClipTimedOverlayPayload,
    ClipTimedSfxCreatePayload,
    ClipTimedSfxPatchPayload,
    ClipTimedSfxPayload,
    GateApprovalResultPayload,
)
from server.apps.clips.preview_render import (
    PREVIEW_CACHE_TIMEOUT,
    PREVIEW_STALL_ERROR,
    invalidate_preview_cache,
    is_preview_job_stale,
    preview_cache_key,
    preview_config_version,
    preview_job_entry,
)
from server.apps.clips.selectors import (
    get_candidate_source_dimensions,
    get_run_source_asset_id,
)
from server.apps.pipelines.enqueue import kiq_advance_pipeline
from server.common.exceptions import ConflictError
from server.common.pagination import paginate_queryset
from server.common.storage import PresignUrlHelper
from server.common.taskiq_sender import kiq_render_task

if TYPE_CHECKING:
    from server.apps.clips.models import (
        ClipCandidate,
        ClipLayoutConfig,
        ClipPost,
        ClipStyleConfig,
        ClipTimedOverlay,
        ClipTimedSfx,
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


def _apply_layout_composition_patch(
    config: 'ClipLayoutConfig',
    payload: ClipLayoutConfigPatchPayload,
) -> list[str]:
    """Apply composition fields and keep fit_mode in sync."""
    has_composition = any(
        getattr(payload, name) is not None
        for name in (
            'foreground_treatment',
            'background_mode',
            'background_color',
            'blur_strength',
        )
    )
    updates: list[str] = []
    if has_composition:
        treatment = (
            normalize_foreground_treatment(payload.foreground_treatment)
            if payload.foreground_treatment is not None
            else config.foreground_treatment
        )
        bg_mode = (
            normalize_background_mode(payload.background_mode)
            if payload.background_mode is not None
            else config.background_mode
        )
        color = (
            normalize_background_color(payload.background_color)
            if payload.background_color is not None
            else config.background_color
        )
        blur = (
            normalize_blur_strength(payload.blur_strength)
            if payload.blur_strength is not None
            else config.blur_strength
        )
        config.foreground_treatment = treatment
        config.background_mode = bg_mode
        config.background_color = color
        config.blur_strength = blur
        updates.extend(
            [
                'foreground_treatment',
                'background_mode',
                'background_color',
                'blur_strength',
            ],
        )
        derived_fit = fit_mode_from_composition(
            foreground_treatment=treatment,
            background_mode=bg_mode,
        )
        if payload.fit_mode is not None and payload.fit_mode != derived_fit:
            msg = (
                'fit_mode conflicts with foreground_treatment/'
                'background_mode composition'
            )
            raise ValidationError(msg)
        if config.fit_mode != derived_fit:
            config.fit_mode = derived_fit
            updates.append('fit_mode')
        return updates

    if payload.fit_mode is None:
        return updates

    if payload.fit_mode not in FitMode.values:
        msg = f'Invalid fit_mode: {payload.fit_mode}'
        raise ValidationError(msg)
    treatment, bg_mode, color, blur = resolve_composition(
        foreground_treatment=None,
        background_mode=None,
        background_color=None,
        blur_strength=None,
        fit_mode=payload.fit_mode,
    )
    config.fit_mode = payload.fit_mode
    config.foreground_treatment = treatment
    config.background_mode = bg_mode
    config.background_color = color
    config.blur_strength = blur
    updates.extend(
        [
            'fit_mode',
            'foreground_treatment',
            'background_mode',
            'background_color',
            'blur_strength',
        ],
    )
    return updates


def _require_asset_uuid(value: str, field_name: str) -> uuid.UUID:
    """Parse a required asset UUID, raising ValidationError when invalid."""
    trimmed = value.strip()
    if not trimmed:
        msg = f'{field_name} is required'
        raise ValidationError(msg)
    try:
        return uuid.UUID(trimmed)
    except ValueError as exc:
        msg = f'Invalid {field_name}: {value}'
        raise ValidationError(msg) from exc


def _config_version(candidate_id: str) -> int:
    """Return a monotonic-ish version from candidate + config timestamps."""
    return preview_config_version(candidate_id)


def _preview_ready_payload(
    presign: PresignUrlHelper,
    candidate_id: str,
    version: int,
) -> ClipPreviewStatusPayload:
    """Build a ready preview status payload with a presigned URL."""
    from server.apps.assets.models import Asset  # noqa: PLC0415
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    candidate = ClipCandidate.objects.get(id=candidate_id)
    asset_id = candidate.preview_asset_id or candidate.render_asset_id
    if asset_id is None:
        return ClipPreviewStatusPayload(
            candidate_id=candidate_id,
            status='queued',
            url=None,
            config_version=version,
        )
    asset = Asset.objects.get(id=asset_id)
    return ClipPreviewStatusPayload(
        candidate_id=candidate_id,
        status='ready',
        url=presign.presign_get(asset.file.name or ''),
        config_version=version,
    )


def _preview_queued_payload(
    candidate_id: str,
    version: int,
) -> ClipPreviewStatusPayload:
    return ClipPreviewStatusPayload(
        candidate_id=candidate_id,
        status='queued',
        url=None,
        config_version=version,
    )


def _preview_failed_payload(
    candidate_id: str,
    version: int,
    error: str,
) -> ClipPreviewStatusPayload:
    return ClipPreviewStatusPayload(
        candidate_id=candidate_id,
        status='failed',
        url=None,
        config_version=version,
        error=error[:500],
    )


def _preview_poll_status_from_cache(
    cached: dict[str, object],
    *,
    candidate_id: str,
    presign: PresignUrlHelper | None = None,
) -> ClipPreviewStatusPayload | None:
    """Map a cached job entry to a poll response without hitting Postgres.

    Uses ``config_version`` and ``asset_file_name`` stored on the cache entry
    so active polls are a single Redis read (+ local URL signing when ready).
    """
    raw_version = cached.get('config_version')
    version = int(raw_version) if isinstance(raw_version, int) else 0
    cached_status = cached.get('status')
    if cached_status in {'queued', 'rendering'}:
        if is_preview_job_stale(cached):
            invalidate_preview_cache(candidate_id)
            return _preview_failed_payload(
                candidate_id,
                version,
                PREVIEW_STALL_ERROR,
            )
        return _preview_queued_payload(candidate_id, version)
    if cached_status == 'failed':
        raw_error = cached.get('error')
        error = (
            str(raw_error)[:500]
            if isinstance(raw_error, str) and raw_error
            else None
        )
        return ClipPreviewStatusPayload(
            candidate_id=candidate_id,
            status='failed',
            url=None,
            config_version=version,
            error=error,
        )
    if cached_status == 'ready' and presign is not None:
        raw_name = cached.get('asset_file_name')
        if isinstance(raw_name, str) and raw_name:
            return ClipPreviewStatusPayload(
                candidate_id=candidate_id,
                status='ready',
                url=presign.presign_get(raw_name),
                config_version=version,
            )
    return None


def _preview_status_from_cache(
    cached: dict[str, object],
    *,
    candidate_id: str,
    version: int,
    presign: PresignUrlHelper,
    force: bool,
) -> ClipPreviewStatusPayload | None:
    cached_status = cached.get('status')
    if cached_status in {'queued', 'rendering'}:
        if is_preview_job_stale(cached):
            return None
        return _preview_queued_payload(candidate_id, version)
    if (
        not force
        and cached_status == 'ready'
        and cached.get('config_version') == version
    ):
        raw_name = cached.get('asset_file_name')
        if isinstance(raw_name, str) and raw_name:
            return ClipPreviewStatusPayload(
                candidate_id=candidate_id,
                status='ready',
                url=presign.presign_get(raw_name),
                config_version=version,
            )
        return _preview_ready_payload(presign, candidate_id, version)
    return None


def _claim_preview_slot(
    cache: BaseCache,
    cache_key: str,
    queued_entry: dict[str, object],
    *,
    force: bool,
) -> bool:
    if cache.add(cache_key, queued_entry, timeout=PREVIEW_CACHE_TIMEOUT):
        return True
    if force:
        cache.set(cache_key, queued_entry, timeout=PREVIEW_CACHE_TIMEOUT)
        return True
    return False


def _cached_preview_trigger_response(
    cache: BaseCache,
    cache_key: str,
    *,
    candidate_id: str,
    version: int,
    presign: PresignUrlHelper,
    force: bool,
) -> ClipPreviewStatusPayload | None:
    cached = cache.get(cache_key)
    if not isinstance(cached, dict):
        return None
    return _preview_status_from_cache(
        cached,
        candidate_id=candidate_id,
        version=version,
        presign=presign,
        force=force,
    )


def _prepare_preview_cache_state(
    cache: BaseCache,
    cache_key: str,
    candidate_id: str,
    *,
    force: bool,
) -> None:
    if force:
        invalidate_preview_cache(candidate_id)
        return
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and (
        cached.get('status') == 'failed' or is_preview_job_stale(cached)
    ):
        invalidate_preview_cache(candidate_id)


def _enqueue_clip_preview(
    candidate_id: str,
    presign: PresignUrlHelper,
    *,
    force: bool,
) -> ClipPreviewStatusPayload:
    from django.core.cache import cache  # noqa: PLC0415

    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415
    from server.apps.clips.tasks import (  # noqa: PLC0415
        render_clip_preview_task,
    )

    ClipCandidate.objects.get(id=candidate_id)
    version = _config_version(candidate_id)
    cache_key = preview_cache_key(candidate_id)

    if not force:
        short_circuit = _cached_preview_trigger_response(
            cache,
            cache_key,
            candidate_id=candidate_id,
            version=version,
            presign=presign,
            force=force,
        )
        if short_circuit is not None:
            return short_circuit
    _prepare_preview_cache_state(
        cache,
        cache_key,
        candidate_id,
        force=force,
    )

    queued_entry = preview_job_entry('queued', version)
    if not _claim_preview_slot(
        cache,
        cache_key,
        queued_entry,
        force=force,
    ):
        short_circuit = _cached_preview_trigger_response(
            cache,
            cache_key,
            candidate_id=candidate_id,
            version=version,
            presign=presign,
            force=force,
        )
        if short_circuit is not None:
            return short_circuit
        return _preview_queued_payload(candidate_id, version)

    try:
        kiq_render_task(render_clip_preview_task, candidate_id)
    except Exception as exc:
        error = f'Could not queue preview render: {exc}'
        cache.set(
            cache_key,
            {'status': 'failed', 'error': error[:500]},
            timeout=PREVIEW_CACHE_TIMEOUT,
        )
        return _preview_failed_payload(candidate_id, version, error)
    return _preview_queued_payload(candidate_id, version)


def _beats_payload(raw_beats: object) -> list[ClipBeatPayload]:
    """Map ClipCandidate.beats JSON into API beat payloads."""
    if not isinstance(raw_beats, list):
        return []
    result: list[ClipBeatPayload] = []
    max_beats = 3
    for idx, item in enumerate(raw_beats[:max_beats]):
        assert idx < max_beats  # noqa: S101
        if not isinstance(item, dict):
            continue
        result.append(
            ClipBeatPayload(
                role=str(item.get('role', '')),
                start_sec=float(item.get('start_sec', 0) or 0),
                end_sec=float(item.get('end_sec', 0) or 0),
                label=str(item.get('label', '') or ''),
                note=str(item.get('note', '') or ''),
            ),
        )
    return result


def _to_candidate_payload(candidate: 'ClipCandidate') -> ClipCandidatePayload:
    from server.apps.clips.logic.constants import (  # noqa: PLC0415
        score_to_letter_grade,
    )

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
        headline=candidate.headline,
        hook_score=candidate.hook_score,
        flow_score=candidate.flow_score,
        value_score=candidate.value_score,
        trend_score=candidate.trend_score,
        virality_score=candidate.virality_score,
        intent_match_score=candidate.intent_match_score,
        confidence=candidate.confidence,
        score_version=candidate.score_version,
        hook_reason=candidate.hook_reason,
        flow_reason=candidate.flow_reason,
        value_reason=candidate.value_reason,
        trend_reason=candidate.trend_reason,
        hook_grade=score_to_letter_grade(candidate.hook_score),
        flow_grade=score_to_letter_grade(candidate.flow_score),
        value_grade=score_to_letter_grade(candidate.value_score),
        trend_grade=score_to_letter_grade(candidate.trend_score),
        arrangement=getattr(candidate, 'arrangement', '') or 'contiguous',
        beats=_beats_payload(getattr(candidate, 'beats', None)),
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
        fit_mode=config.fit_mode,
        foreground_treatment=config.foreground_treatment,
        background_mode=config.background_mode,
        background_color=config.background_color,
        blur_strength=config.blur_strength,
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
        caption_font_asset_id=(
            str(config.caption_font_asset_id)
            if config.caption_font_asset_id is not None
            else None
        ),
        caption_highlight_color=config.caption_highlight_color,
        caption_uppercase=config.caption_uppercase,
        emoji_keyword_map=dict(config.emoji_keyword_map),
        hook_enabled=config.hook_enabled,
        hook_style=config.hook_style,
        hook_duration_sec=config.hook_duration_sec,
        hook_font=config.hook_font,
        hook_size=config.hook_size,
        hook_color=config.hook_color,
        hook_bg_color=config.hook_bg_color,
        hook_font_asset_id=(
            str(config.hook_font_asset_id)
            if config.hook_font_asset_id is not None
            else None
        ),
        hook_animation=config.hook_animation,
        intro_transition=config.intro_transition,
        outro_transition=config.outro_transition,
        intro_transition_duration_sec=config.intro_transition_duration_sec,
        outro_transition_duration_sec=config.outro_transition_duration_sec,
        intro_transition_asset_id=(
            str(config.intro_transition_asset_id)
            if config.intro_transition_asset_id is not None
            else None
        ),
        outro_transition_asset_id=(
            str(config.outro_transition_asset_id)
            if config.outro_transition_asset_id is not None
            else None
        ),
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
        watermark_color=config.watermark_color,
        watermark_font=config.watermark_font,
        watermark_font_asset_id=(
            str(config.watermark_font_asset_id)
            if config.watermark_font_asset_id is not None
            else None
        ),
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
        color_filter=config.color_filter,
        brightness=config.brightness,
        contrast=config.contrast,
        saturation=config.saturation,
        lut_asset_id=(
            str(config.lut_asset_id)
            if config.lut_asset_id is not None
            else None
        ),
        playback_speed=config.playback_speed,
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
        video_asset_id=(
            str(overlay.video_asset_id)
            if overlay.video_asset_id is not None
            else None
        ),
        shape=overlay.shape,
        start_sec=overlay.start_sec,
        end_sec=overlay.end_sec,
        x=overlay.x,
        y=overlay.y,
        font_size=overlay.font_size,
        color=overlay.color,
        opacity=overlay.opacity,
        font=overlay.font,
        font_asset_id=(
            str(overlay.font_asset_id)
            if overlay.font_asset_id is not None
            else None
        ),
        width=overlay.width,
        animation=overlay.animation,
    )


def _to_sfx_payload(sfx: 'ClipTimedSfx') -> ClipTimedSfxPayload:
    return ClipTimedSfxPayload(
        id=str(sfx.id),
        candidate_id=str(sfx.candidate_id),
        sfx_asset_id=str(sfx.sfx_asset_id),
        start_sec=sfx.start_sec,
        volume_db=sfx.volume_db,
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
            ).order_by('-virality_score', '-relevance_score')
        ]

    def get_by_id(self, candidate_id: str) -> ClipCandidatePayload:
        """Return a single candidate by ID."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        return _to_candidate_payload(
            ClipCandidate.objects.select_related('run').get(id=candidate_id),
        )

    def duplicate(self, candidate_id: str) -> ClipCandidatePayload:
        """Clone a candidate with its layout and style configs."""
        from django.db import transaction  # noqa: PLC0415

        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipLayoutConfig,
            ClipStyleConfig,
        )

        with transaction.atomic():
            source = ClipCandidate.objects.select_related(
                'run',
                'layout_config',
                'style_config',
            ).get(id=candidate_id)
            clone = ClipCandidate.objects.create(
                run=source.run,
                start_sec=source.start_sec,
                end_sec=source.end_sec,
                title=f'{source.title} (copy)'[:200],
                hook_text=source.hook_text,
                headline=source.headline,
                caption_template=source.caption_template,
                relevance_score=source.relevance_score,
                hook_score=source.hook_score,
                flow_score=source.flow_score,
                value_score=source.value_score,
                trend_score=source.trend_score,
                virality_score=source.virality_score,
                intent_match_score=source.intent_match_score,
                confidence=source.confidence,
                score_version=source.score_version,
                hook_reason=source.hook_reason,
                flow_reason=source.flow_reason,
                value_reason=source.value_reason,
                trend_reason=source.trend_reason,
                reason=source.reason,
                transcript_excerpt=source.transcript_excerpt,
                beats=list(source.beats or []),
                arrangement=source.arrangement,
                status=CandidateStatus.PROPOSED,
                is_manual=True,
            )
            # Signal creates empty configs; overwrite from source.
            layout = clone.layout_config
            src_layout = source.layout_config
            for field in (
                f.name
                for f in ClipLayoutConfig._meta.fields
                if f.name not in {'id', 'candidate', 'created_at', 'updated_at'}
            ):
                setattr(layout, field, getattr(src_layout, field))
            layout.save()
            style = clone.style_config
            src_style = source.style_config
            for field in (
                f.name
                for f in ClipStyleConfig._meta.fields
                if f.name not in {'id', 'candidate', 'created_at', 'updated_at'}
            ):
                setattr(style, field, getattr(src_style, field))
            style.save()
        return _to_candidate_payload(
            ClipCandidate.objects.select_related('run').get(id=clone.id),
        )

    def list_caption_presets(self) -> CaptionPresetListPayload:
        """Return the seeded caption preset gallery."""
        from server.apps.clips.caption_presets import (  # noqa: PLC0415
            list_caption_presets,
        )

        return CaptionPresetListPayload(
            items=[
                CaptionPresetPayload(**preset)
                for preset in list_caption_presets()
            ],
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
            invalidate_preview_cache(candidate_id)
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

    def start_render(
        self,
        run_id: str,
        approved_candidate_ids: list[str] | None = None,
    ) -> GateApprovalResultPayload:
        """Resume clip_approval_gate and enqueue clip_render."""
        self._assert_clip_approval_gate_parked(run_id)
        candidate_ids = self._resolve_start_render_candidate_ids(
            run_id,
            approved_candidate_ids,
        )
        if not candidate_ids:
            msg = 'Approve at least one candidate before starting render.'
            raise ValidationError(msg)
        return self.approve_gate(run_id, candidate_ids)

    def _resolve_start_render_candidate_ids(
        self,
        run_id: str,
        approved_candidate_ids: list[str] | None,
    ) -> list[str]:
        if approved_candidate_ids:
            return approved_candidate_ids
        return [payload.id for payload in self.approved_for_run(run_id)]

    def _assert_clip_approval_gate_parked(self, run_id: str) -> None:
        from server.apps.pipelines.logic.constants import (  # noqa: PLC0415
            GATE_PARKED_STATUSES,
        )
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineRun,
            RunStatus,
            StageExecution,
        )

        run = PipelineRun.objects.get(id=uuid.UUID(run_id))
        gate_parked = StageExecution.objects.filter(
            run=run,
            stage_key='clip_approval_gate',
            parent=None,
            status__in=GATE_PARKED_STATUSES,
        ).exists()
        if run.status != RunStatus.AWAITING_REVIEW or not gate_parked:
            msg = 'Run is not waiting at clip approval gate'
            raise ConflictError(msg)

    def approve_gate(
        self,
        run_id: str,
        approved_candidate_ids: list[str],
    ) -> GateApprovalResultPayload:
        """Sync candidates and resume the clip approval gate."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _approve_gate_sync,
        )

        count = self.sync_gate_candidates(run_id, approved_candidate_ids)
        output: dict[str, Any] = {
            'approved_candidate_ids': approved_candidate_ids,
        }
        _approve_gate_sync(run_id, 'clip_approval_gate', output)
        kiq_advance_pipeline(run_id)
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
        composition_fields = _apply_layout_composition_patch(config, payload)
        update_fields.extend(composition_fields)
        if update_fields:
            config.save(update_fields=update_fields)
            invalidate_preview_cache(candidate_id)
        source_w, source_h = get_candidate_source_dimensions(candidate_id)
        return _to_layout_payload(
            config,
            source_width=source_w,
            source_height=source_h,
        )

    def reset_smart_crop(self, candidate_id: str) -> ClipLayoutConfigPayload:
        """Clear manual crop and enqueue worker smart-crop detection."""
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipLayoutConfig,
        )
        from server.apps.clips.tasks import (  # noqa: PLC0415
            reset_smart_crop_task,
        )

        ClipCandidate.objects.get(id=candidate_id)
        config = ClipLayoutConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        config.render_mode = RenderMode.SMART_CROP
        config.manual_crop_x = None
        config.manual_crop_y = None
        config.manual_crop_w = None
        config.manual_crop_h = None
        config.face_detected = None
        config.detection_confidence = None
        config.save(
            update_fields=[
                'render_mode',
                'manual_crop_x',
                'manual_crop_y',
                'manual_crop_w',
                'manual_crop_h',
                'face_detected',
                'detection_confidence',
                'updated_at',
            ],
        )
        invalidate_preview_cache(candidate_id)
        kiq_render_task(reset_smart_crop_task, candidate_id)
        source_w, source_h = get_candidate_source_dimensions(candidate_id)
        return _to_layout_payload(
            config,
            source_width=source_w,
            source_height=source_h,
        )

    def apply_smart_crop_detection(
        self,
        candidate_id: str,
    ) -> ClipLayoutConfigPayload:
        """Run MediaPipe detection on the worker and persist crop fields."""
        import tempfile  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipLayoutConfig,
        )
        from server.apps.rendering.speaker_detection import (  # noqa: PLC0415
            SpeakerDetectionService,
            clamp_crop_rect,
        )

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        config = ClipLayoutConfig.objects.get(candidate_id=candidate_id)  # type: ignore[misc]
        asset_id = get_run_source_asset_id(str(candidate.run_id))
        update_fields = [
            'face_detected',
            'detection_confidence',
            'updated_at',
        ]
        if asset_id is None:
            config.face_detected = False
            config.detection_confidence = 0.0
            config.save(update_fields=update_fields)
        else:
            asset = Asset.objects.get(id=uuid.UUID(asset_id))
            with tempfile.NamedTemporaryFile(
                suffix='.mp4',
                delete=False,
            ) as tmp:
                tmp_path = tmp.name
            target_w, target_h = render_format_dimensions(
                config.render_format,
            )
            try:
                from server.common.asset_cache import (  # noqa: PLC0415
                    materialize_to_path,
                )

                materialize_to_path(
                    checksum=asset.checksum,
                    open_stream=lambda: asset.file.open('rb'),
                    destination=Path(tmp_path),
                )
                result = SpeakerDetectionService().detect(
                    video_path=Path(tmp_path),
                    start_sec=candidate.start_sec,
                    end_sec=candidate.end_sec,
                    target_width=target_w,
                    target_height=target_h,
                )
                source_w, source_h = get_candidate_source_dimensions(
                    candidate_id,
                )
                crop_x = result.crop_x
                crop_y = result.crop_y
                crop_w = result.crop_w
                crop_h = result.crop_h
                if (
                    isinstance(source_w, int)
                    and isinstance(source_h, int)
                    and source_w > 0
                    and source_h > 0
                ):
                    clamped = clamp_crop_rect(
                        crop_x,
                        crop_y,
                        crop_w,
                        crop_h,
                        source_w,
                        source_h,
                    )
                    if clamped is not None:
                        crop_x, crop_y, crop_w, crop_h = clamped
                config.manual_crop_x = crop_x
                config.manual_crop_y = crop_y
                config.manual_crop_w = crop_w
                config.manual_crop_h = crop_h
                config.face_detected = result.face_detected
                config.detection_confidence = result.confidence
                update_fields.extend(
                    [
                        'manual_crop_x',
                        'manual_crop_y',
                        'manual_crop_w',
                        'manual_crop_h',
                    ],
                )
                config.save(update_fields=update_fields)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        invalidate_preview_cache(candidate_id)
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
                'caption_highlight_color',
                'caption_uppercase',
                'hook_enabled',
                'hook_style',
                'hook_duration_sec',
                'hook_font',
                'hook_size',
                'hook_color',
                'hook_bg_color',
                'hook_animation',
                'intro_transition',
                'outro_transition',
                'intro_transition_duration_sec',
                'outro_transition_duration_sec',
                'watermark_enabled',
                'watermark_type',
                'watermark_text',
                'watermark_position',
                'watermark_opacity',
                'watermark_size',
                'watermark_color',
                'watermark_font',
                'progress_bar_enabled',
                'progress_bar_position',
                'progress_bar_color',
                'progress_bar_height',
                'music_enabled',
                'music_volume_db',
                'music_fade_in_sec',
                'music_fade_out_sec',
                'color_filter',
                'brightness',
                'contrast',
                'saturation',
                'playback_speed',
            ),
        )
        fk_map = {
            'watermark_image_id': payload.watermark_image_id,
            'intro_asset_id': payload.intro_asset_id,
            'outro_asset_id': payload.outro_asset_id,
            'music_asset_id': payload.music_asset_id,
            'caption_font_asset_id': payload.caption_font_asset_id,
            'hook_font_asset_id': payload.hook_font_asset_id,
            'intro_transition_asset_id': payload.intro_transition_asset_id,
            'outro_transition_asset_id': payload.outro_transition_asset_id,
            'watermark_font_asset_id': payload.watermark_font_asset_id,
            'lut_asset_id': payload.lut_asset_id,
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
            invalidate_preview_cache(candidate_id)
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
            video_asset_id=(
                uuid.UUID(payload.video_asset_id)
                if payload.video_asset_id
                else None
            ),
            shape=payload.shape,
            start_sec=payload.start_sec,
            end_sec=payload.end_sec,
            x=payload.x,
            y=payload.y,
            font_size=payload.font_size,
            color=payload.color,
            opacity=payload.opacity,
            font=payload.font,
            font_asset_id=(
                uuid.UUID(payload.font_asset_id)
                if payload.font_asset_id
                else None
            ),
            width=payload.width,
            animation=payload.animation,
        )
        invalidate_preview_cache(candidate_id)
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
                'shape',
                'font',
                'width',
                'animation',
            ),
        )
        fk_map = {
            'image_asset_id': payload.image_asset_id,
            'video_asset_id': payload.video_asset_id,
            'font_asset_id': payload.font_asset_id,
        }
        for field_name, value in fk_map.items():
            if value is not None:
                setattr(
                    overlay,
                    field_name,
                    uuid.UUID(value) if value else None,
                )
                update_fields.append(field_name)
        if update_fields:
            overlay.save(update_fields=update_fields)
            invalidate_preview_cache(candidate_id)
        return _to_overlay_payload(overlay)

    def delete_overlay(self, candidate_id: str, overlay_id: str) -> None:
        """Delete a timed overlay."""
        from server.apps.clips.models import ClipTimedOverlay  # noqa: PLC0415

        deleted, _ = ClipTimedOverlay.objects.filter(  # type: ignore[misc]
            id=overlay_id,
            candidate_id=candidate_id,
        ).delete()
        if deleted:
            invalidate_preview_cache(candidate_id)

    def list_sfx(
        self,
        candidate_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipSfxListPayload:
        """Return paginated timed SFX drops for a candidate."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        qs = ClipTimedSfx.objects.filter(  # type: ignore[misc]
            candidate_id=candidate_id,
        ).order_by('start_sec', '-id')
        rows, next_cursor, total = paginate_queryset(
            qs,
            cursor=cursor,
            limit=limit,
        )
        return ClipSfxListPayload(
            items=[_to_sfx_payload(row) for row in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def create_sfx(
        self,
        candidate_id: str,
        payload: ClipTimedSfxCreatePayload,
    ) -> ClipTimedSfxPayload:
        """Create a timed SFX drop on a candidate."""
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipTimedSfx,
        )

        sfx_asset_uuid = _require_asset_uuid(
            payload.sfx_asset_id,
            'sfx_asset_id',
        )
        ClipCandidate.objects.get(id=candidate_id)
        sfx = ClipTimedSfx.objects.create(
            candidate_id=candidate_id,
            sfx_asset_id=sfx_asset_uuid,
            start_sec=payload.start_sec,
            volume_db=payload.volume_db,
        )
        invalidate_preview_cache(candidate_id)
        return _to_sfx_payload(sfx)

    def get_sfx(self, candidate_id: str, sfx_id: str) -> ClipTimedSfxPayload:
        """Return one timed SFX drop."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        sfx = ClipTimedSfx.objects.get(  # type: ignore[misc]
            id=sfx_id,
            candidate_id=candidate_id,
        )
        return _to_sfx_payload(sfx)

    def patch_sfx(
        self,
        candidate_id: str,
        sfx_id: str,
        payload: ClipTimedSfxPatchPayload,
    ) -> ClipTimedSfxPayload:
        """Update a timed SFX drop."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        sfx = ClipTimedSfx.objects.get(  # type: ignore[misc]
            id=sfx_id,
            candidate_id=candidate_id,
        )
        update_fields = _apply_patch_fields(
            sfx,
            payload,
            ('start_sec', 'volume_db'),
        )
        if payload.sfx_asset_id is not None:
            sfx.sfx_asset_id = _require_asset_uuid(
                payload.sfx_asset_id,
                'sfx_asset_id',
            )
            update_fields.append('sfx_asset_id')
        if update_fields:
            sfx.save(update_fields=update_fields)
            invalidate_preview_cache(candidate_id)
        return _to_sfx_payload(sfx)

    def delete_sfx(self, candidate_id: str, sfx_id: str) -> None:
        """Delete a timed SFX drop."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        deleted, _ = ClipTimedSfx.objects.filter(  # type: ignore[misc]
            id=sfx_id,
            candidate_id=candidate_id,
        ).delete()
        if deleted:
            invalidate_preview_cache(candidate_id)

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
        """Return export job state + presigned URL for the render asset."""
        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.export_render import (  # noqa: PLC0415
            get_export_state,
        )
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.get(id=candidate_id)
        asset_id: str | None = None
        url: str | None = None
        if candidate.render_asset_id is not None:
            asset = Asset.objects.get(id=candidate.render_asset_id)
            asset_id = str(asset.id)
            url = self._presign.presign_get(asset.file.name or '')

        state = get_export_state(candidate_id)
        if state is not None and state.get('status') in {
            'queued',
            'rendering',
            'failed',
        }:
            error = state.get('error')
            return ClipRenderPayload(
                candidate_id=candidate_id,
                asset_id=asset_id,
                url=url,
                status=str(state['status']),
                error=str(error) if error is not None else None,
            )
        return ClipRenderPayload(
            candidate_id=candidate_id,
            asset_id=asset_id,
            url=url,
            status='ready' if asset_id is not None else 'idle',
        )

    def trigger_render(self, candidate_id: str) -> ClipRenderPayload:
        """Queue a full-quality export render for one candidate."""
        from server.apps.clips.export_render import (  # noqa: PLC0415
            get_export_state,
            set_export_queued,
        )
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415
        from server.apps.clips.tasks import (  # noqa: PLC0415
            render_clip_export_task,
        )

        candidate = ClipCandidate.objects.get(id=candidate_id)
        if candidate.status not in {
            CandidateStatus.APPROVED,
            CandidateStatus.RENDERED,
        }:
            msg = (
                f'Candidate must be approved before export '
                f'(status: {candidate.status})'
            )
            raise ConflictError(msg)

        state = get_export_state(candidate_id)
        if state is not None and state.get('status') in {
            'queued',
            'rendering',
        }:
            return self.get_render(candidate_id)

        set_export_queued(candidate_id)
        kiq_render_task(render_clip_export_task, candidate_id)
        return self.get_render(candidate_id)

    def trigger_preview(
        self,
        candidate_id: str,
        *,
        force: bool = False,
    ) -> ClipPreviewStatusPayload:
        """Queue a lightweight preview render for one candidate."""
        return _enqueue_clip_preview(
            candidate_id,
            self._presign,
            force=force,
        )

    def get_preview_status(
        self,
        candidate_id: str,
    ) -> ClipPreviewStatusPayload:
        """Return preview job state for one candidate.

        Active cache entries (queued/rendering/failed/ready with a stored
        file name) are served from Redis only — no Postgres round trips.
        Idle and expired-cache paths fall back to the database.
        """
        from django.core.cache import cache  # noqa: PLC0415

        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        cached = cache.get(preview_cache_key(candidate_id))
        if isinstance(cached, dict):
            from_cache = _preview_poll_status_from_cache(
                cached,
                candidate_id=candidate_id,
                presign=self._presign,
            )
            if from_cache is not None:
                return from_cache

        version = _config_version(candidate_id)
        candidate = ClipCandidate.objects.get(id=candidate_id)
        if candidate.preview_asset_id is not None:
            asset = Asset.objects.get(id=candidate.preview_asset_id)
            return ClipPreviewStatusPayload(
                candidate_id=candidate_id,
                status='ready',
                url=self._presign.presign_get(asset.file.name or ''),
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
        """Extract a JPEG frame from the source video at the given time.

        Results are cached by source checksum and quantized timestamp so
        repeated editor loads do not re-download or re-encode.
        """
        import hashlib
        import subprocess  # noqa: S404
        import tempfile
        from pathlib import Path

        from django.core.cache import cache  # noqa: PLC0415
        from django.core.files.base import ContentFile  # noqa: PLC0415

        from server.apps.assets.models import Asset, AssetKind  # noqa: PLC0415
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415
        from server.common.asset_cache import (  # noqa: PLC0415
            materialize_to_path,
        )

        candidate = ClipCandidate.objects.select_related('run').get(
            id=candidate_id,
        )
        clamped = max(
            candidate.start_sec,
            min(time_sec, candidate.end_sec),
        )
        quantized = round(clamped, 2)
        asset_id = get_run_source_asset_id(str(candidate.run_id))
        if asset_id is None:
            msg = 'Source video not available for this candidate'
            raise ValueError(msg)

        source_asset = Asset.objects.get(id=uuid.UUID(asset_id))
        source_w, source_h = get_candidate_source_dimensions(candidate_id)
        frame_key = (
            f'clip_source_frame:{source_asset.checksum}:{quantized}'
        )
        cached_frame = cache.get(frame_key)
        if isinstance(cached_frame, dict):
            raw_name = cached_frame.get('file_name')
            if isinstance(raw_name, str) and raw_name:
                return ClipSourceFramePayload(
                    candidate_id=candidate_id,
                    time_sec=quantized,
                    url=self._presign.presign_get(raw_name),
                    width=source_w,
                    height=source_h,
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / 'source.mp4'
            frame_path = Path(tmpdir) / 'frame.jpg'
            materialize_to_path(
                checksum=source_asset.checksum,
                open_stream=lambda: source_asset.file.open('rb'),
                destination=video_path,
            )
            cmd = [
                'ffmpeg',
                '-y',
                '-ss',
                f'{quantized:.3f}',
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
            f'source_frame_{candidate_id}_{int(quantized)}.jpg',
            ContentFile(frame_bytes),
            save=False,
        )
        thumb.save()
        file_name = thumb.file.name or ''
        cache.set(
            frame_key,
            {'file_name': file_name},
            timeout=86_400,
        )
        return ClipSourceFramePayload(
            candidate_id=candidate_id,
            time_sec=quantized,
            url=self._presign.presign_get(file_name),
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
