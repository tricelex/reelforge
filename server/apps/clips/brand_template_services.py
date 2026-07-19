"""CRUD for clip brand templates."""

import uuid
from datetime import datetime
from typing import final

import attrs
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.clips.logic.composition import (
    fit_mode_from_composition,
    normalize_background_color,
    normalize_background_mode,
    normalize_blur_strength,
    normalize_foreground_treatment,
)
from server.apps.clips.logic.constants import (
    BackgroundMode,
    FitMode,
    ForegroundTreatment,
    RenderFormat,
    RenderMode,
    WatermarkPosition,
)
from server.apps.clips.logic.value_objects import (
    ClipBrandTemplateCreatePayload,
    ClipBrandTemplateListPayload,
    ClipBrandTemplatePatchPayload,
    ClipBrandTemplatePayload,
)
from server.apps.clips.models import ClipBrandTemplate

_VALID_FORMATS = frozenset(RenderFormat.values)
_VALID_MODES = frozenset(RenderMode.values)
_VALID_FITS = frozenset(FitMode.values)
_VALID_FOREGROUND = frozenset(ForegroundTreatment.values)
_VALID_BACKGROUND = frozenset(BackgroundMode.values)
_VALID_POSITIONS = frozenset(WatermarkPosition.values)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _asset_id(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _to_payload(template: ClipBrandTemplate) -> ClipBrandTemplatePayload:
    return ClipBrandTemplatePayload(
        id=str(template.id),
        channel_id=str(template.channel_id),
        name=template.name,
        archived=template.archived,
        render_format=template.render_format,
        render_mode=template.render_mode,
        fit_mode=template.fit_mode,
        foreground_treatment=template.foreground_treatment,
        background_mode=template.background_mode,
        background_color=template.background_color,
        blur_strength=template.blur_strength,
        caption_preset_key=template.caption_preset_key,
        logo_asset_id=_asset_id(template.logo_asset_id),
        logo_position=template.logo_position,
        logo_opacity=template.logo_opacity,
        intro_asset_id=_asset_id(template.intro_asset_id),
        outro_asset_id=_asset_id(template.outro_asset_id),
        music_asset_id=_asset_id(template.music_asset_id),
        music_volume_db=template.music_volume_db,
        keyword_highlighter=template.keyword_highlighter,
        auto_transitions=template.auto_transitions,
        notes=template.notes,
        created_at=_iso(template.created_at),
    )


def _parse_optional_uuid(value: str | None) -> uuid.UUID | None:
    if value is None or not value:
        return None
    return uuid.UUID(value)


def _normalize_patch_scalar(field: str, value: object) -> object:
    if field == 'name':
        return str(value).strip()[:120]
    if field == 'render_format' and value not in _VALID_FORMATS:
        msg = f'Invalid render_format: {value}'
        raise ValidationError(msg)
    if field == 'render_mode' and value not in _VALID_MODES:
        msg = f'Invalid render_mode: {value}'
        raise ValidationError(msg)
    if field == 'fit_mode' and value not in _VALID_FITS:
        msg = f'Invalid fit_mode: {value}'
        raise ValidationError(msg)
    if field == 'foreground_treatment':
        return normalize_foreground_treatment(str(value))
    if field == 'background_mode':
        return normalize_background_mode(str(value))
    if field == 'background_color':
        return normalize_background_color(str(value))
    if field == 'blur_strength':
        return normalize_blur_strength(int(value))  # type: ignore[arg-type]
    if field == 'logo_position' and value not in _VALID_POSITIONS:
        msg = f'Invalid logo_position: {value}'
        raise ValidationError(msg)
    return value


def _apply_scalar_patch(
    template: ClipBrandTemplate,
    payload: ClipBrandTemplatePatchPayload,
) -> list[str]:
    mapping = {
        'name': payload.name,
        'archived': payload.archived,
        'render_format': payload.render_format,
        'render_mode': payload.render_mode,
        'fit_mode': payload.fit_mode,
        'foreground_treatment': payload.foreground_treatment,
        'background_mode': payload.background_mode,
        'background_color': payload.background_color,
        'blur_strength': payload.blur_strength,
        'caption_preset_key': payload.caption_preset_key,
        'logo_position': payload.logo_position,
        'logo_opacity': payload.logo_opacity,
        'music_volume_db': payload.music_volume_db,
        'keyword_highlighter': payload.keyword_highlighter,
        'auto_transitions': payload.auto_transitions,
        'notes': payload.notes,
    }
    updates: list[str] = []
    for field, raw in mapping.items():
        if raw is None:
            continue
        setattr(template, field, _normalize_patch_scalar(field, raw))
        updates.append(field)

    has_composition = any(
        name in updates
        for name in (
            'foreground_treatment',
            'background_mode',
            'background_color',
            'blur_strength',
        )
    )
    if has_composition:
        derived = fit_mode_from_composition(
            foreground_treatment=template.foreground_treatment,
            background_mode=template.background_mode,
        )
        if template.fit_mode != derived:
            template.fit_mode = derived
            if 'fit_mode' not in updates:
                updates.append('fit_mode')
    elif 'fit_mode' in updates:
        from server.apps.clips.logic.composition import (  # noqa: PLC0415
            apply_legacy_fit_mode,
        )

        treatment, bg_mode, color, blur = apply_legacy_fit_mode(
            fit_mode=template.fit_mode,
        )
        template.foreground_treatment = treatment
        template.background_mode = bg_mode
        template.background_color = color
        template.blur_strength = blur
        updates.extend(
            [
                'foreground_treatment',
                'background_mode',
                'background_color',
                'blur_strength',
            ],
        )
    return updates


def _apply_asset_patch(
    template: ClipBrandTemplate,
    payload: ClipBrandTemplatePatchPayload,
) -> list[str]:
    asset_fields = {
        'logo_asset_id': payload.logo_asset_id,
        'intro_asset_id': payload.intro_asset_id,
        'outro_asset_id': payload.outro_asset_id,
        'music_asset_id': payload.music_asset_id,
    }
    updates: list[str] = []
    for field, raw in asset_fields.items():
        if raw is None:
            continue
        if not raw:
            setattr(template, field, None)
        else:
            setattr(template, field, uuid.UUID(raw))
        updates.append(field)
    return updates


@final
@attrs.define(slots=True, frozen=True)
class ClipBrandTemplateService:
    """CRUD for reusable clip brand templates."""

    def list_templates(
        self,
        *,
        channel_id: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> ClipBrandTemplateListPayload:
        """Return brand templates ordered by name."""
        qs = ClipBrandTemplate.objects.order_by('name', 'id')
        if channel_id:
            qs = qs.filter(channel_id=uuid.UUID(channel_id))
        if not include_archived:
            qs = qs.filter(archived=False)
        total = qs.count()
        rows = list(qs[: min(max(limit, 1), 100)])
        return ClipBrandTemplateListPayload(
            items=[_to_payload(row) for row in rows],
            next_cursor=None,
            total=total,
        )

    def get_template(self, template_id: str) -> ClipBrandTemplatePayload:
        """Return one brand template."""
        try:
            template = ClipBrandTemplate.objects.get(id=uuid.UUID(template_id))
        except (ObjectDoesNotExist, ValueError) as exc:
            msg = f'Brand template not found: {template_id}'
            raise ValidationError(msg) from exc
        return _to_payload(template)

    def create_template(
        self,
        payload: ClipBrandTemplateCreatePayload,
    ) -> ClipBrandTemplatePayload:
        """Create a brand template row."""
        from server.apps.channels.models import Channel  # noqa: PLC0415

        try:
            Channel.objects.get(id=uuid.UUID(payload.channel_id))
        except (ObjectDoesNotExist, ValueError) as exc:
            msg = f'Channel not found: {payload.channel_id}'
            raise ValidationError(msg) from exc

        self._validate_enums(payload)
        template = ClipBrandTemplate.objects.create(
            channel_id=payload.channel_id,
            name=payload.name.strip()[:120],
            render_format=payload.render_format,
            render_mode=payload.render_mode,
            fit_mode=payload.fit_mode,
            foreground_treatment=payload.foreground_treatment,
            background_mode=payload.background_mode,
            background_color=normalize_background_color(
                payload.background_color,
            ),
            blur_strength=normalize_blur_strength(payload.blur_strength),
            caption_preset_key=payload.caption_preset_key,
            logo_asset_id=_parse_optional_uuid(payload.logo_asset_id),
            logo_position=payload.logo_position,
            logo_opacity=payload.logo_opacity,
            intro_asset_id=_parse_optional_uuid(payload.intro_asset_id),
            outro_asset_id=_parse_optional_uuid(payload.outro_asset_id),
            music_asset_id=_parse_optional_uuid(payload.music_asset_id),
            music_volume_db=payload.music_volume_db,
            keyword_highlighter=payload.keyword_highlighter,
            auto_transitions=payload.auto_transitions,
            notes=payload.notes,
        )
        return _to_payload(template)

    def patch_template(
        self,
        template_id: str,
        payload: ClipBrandTemplatePatchPayload,
    ) -> ClipBrandTemplatePayload:
        """Update mutable brand template fields."""
        try:
            template = ClipBrandTemplate.objects.get(id=uuid.UUID(template_id))
        except (ObjectDoesNotExist, ValueError) as exc:
            msg = f'Brand template not found: {template_id}'
            raise ValidationError(msg) from exc

        updates = _apply_scalar_patch(template, payload)
        updates.extend(_apply_asset_patch(template, payload))
        if updates:
            updates.append('updated_at')
            template.save(update_fields=updates)
        return _to_payload(template)

    def duplicate_template(
        self,
        template_id: str,
    ) -> ClipBrandTemplatePayload:
        """Clone a brand template as a new editable copy."""
        try:
            source = ClipBrandTemplate.objects.get(id=uuid.UUID(template_id))
        except (ObjectDoesNotExist, ValueError) as exc:
            msg = f'Brand template not found: {template_id}'
            raise ValidationError(msg) from exc
        clone = ClipBrandTemplate.objects.create(
            channel_id=source.channel_id,
            name=f'{source.name} (copy)'[:120],
            archived=False,
            render_format=source.render_format,
            render_mode=source.render_mode,
            fit_mode=source.fit_mode,
            foreground_treatment=source.foreground_treatment,
            background_mode=source.background_mode,
            background_color=source.background_color,
            blur_strength=source.blur_strength,
            caption_preset_key=source.caption_preset_key,
            logo_asset_id=source.logo_asset_id,
            logo_position=source.logo_position,
            logo_opacity=source.logo_opacity,
            intro_asset_id=source.intro_asset_id,
            outro_asset_id=source.outro_asset_id,
            music_asset_id=source.music_asset_id,
            music_volume_db=source.music_volume_db,
            keyword_highlighter=source.keyword_highlighter,
            auto_transitions=source.auto_transitions,
            notes=source.notes,
        )
        return _to_payload(clone)

    def _validate_enums(self, payload: ClipBrandTemplateCreatePayload) -> None:
        if payload.render_format not in _VALID_FORMATS:
            msg = f'Invalid render_format: {payload.render_format}'
            raise ValidationError(msg)
        if payload.render_mode not in _VALID_MODES:
            msg = f'Invalid render_mode: {payload.render_mode}'
            raise ValidationError(msg)
        if payload.fit_mode not in _VALID_FITS:
            msg = f'Invalid fit_mode: {payload.fit_mode}'
            raise ValidationError(msg)
        if payload.foreground_treatment not in _VALID_FOREGROUND:
            msg = f'Invalid foreground_treatment: {payload.foreground_treatment}'
            raise ValidationError(msg)
        if payload.background_mode not in _VALID_BACKGROUND:
            msg = f'Invalid background_mode: {payload.background_mode}'
            raise ValidationError(msg)
        if payload.logo_position not in _VALID_POSITIONS:
            msg = f'Invalid logo_position: {payload.logo_position}'
            raise ValidationError(msg)
        _ = normalize_background_color(payload.background_color)
        _ = normalize_blur_strength(payload.blur_strength)
