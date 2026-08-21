"""Jinja2 variable namespace for versioned pipeline prompt templates."""

import uuid
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from server.apps.pipelines.stages.base import StageContext


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _niche_dict(channel: Any) -> dict[str, Any]:
    empty = {
        'audience': '',
        'angle': '',
        'banned_topics': [],
    }
    try:
        niche = getattr(channel, 'niche_config', None)
    except ObjectDoesNotExist:
        return empty
    if niche is None:
        return empty
    return {
        'audience': getattr(niche, 'audience', '') or '',
        'angle': getattr(niche, 'angle', '') or '',
        'banned_topics': list(getattr(niche, 'banned_topics', []) or []),
    }


def _normalize_beat(
    beat: Any,
    pacing: dict[str, Any],
    mood_map: dict[str, Any],
) -> dict[str, Any] | None:
    extra: dict[str, Any]
    if isinstance(beat, str):
        name = beat
        description = ''
        extra = {}
    elif isinstance(beat, dict):
        name = str(beat.get('name', ''))
        description = str(beat.get('description', ''))
        extra = {
            key: val
            for key, val in beat.items()
            if key not in {'name', 'description'}
        }
    else:
        return None
    seconds = extra.get('pacing_seconds', pacing.get(name, 0))
    mood = extra.get('music_mood') or mood_map.get(name, '')
    return {
        **extra,
        'name': name,
        'description': description,
        'pacing_seconds': _as_int(seconds, 0),
        'music_mood': str(mood or ''),
    }


def _normalize_beats(
    beats: Any,
    pacing: dict[str, Any],
    mood_map: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(beats, list):
        return []
    rows: list[dict[str, Any]] = []
    for beat in beats:
        row = _normalize_beat(beat, pacing, mood_map)
        if row is not None:
            rows.append(row)
    return rows


def _format_dict(fmt: Any) -> dict[str, Any]:
    pacing = _as_mapping(getattr(fmt, 'pacing', None))
    mood_map = _as_mapping(getattr(fmt, 'music_mood_map', None))
    return {
        'name': getattr(fmt, 'name', '') or '',
        'key': getattr(fmt, 'key', '') or '',
        'fiction': bool(getattr(fmt, 'fiction', False)),
        'beats': _normalize_beats(getattr(fmt, 'beats', []), pacing, mood_map),
        'narration_pov': getattr(fmt, 'narration_pov', 'narrator')
        or 'narrator',
        'pacing': pacing,
        'music_mood_map': mood_map,
    }


def _channel_dict(channel: Any) -> dict[str, Any]:
    try:
        branding = getattr(channel, 'branding', None)
    except ObjectDoesNotExist:
        branding = None
    branding_vars: dict[str, Any] | None = None
    if branding is not None:
        branding_vars = {
            'thumbnail_palette': (
                getattr(branding, 'thumbnail_palette', {}) or {}
            ),
        }
    return {
        'name': getattr(channel, 'name', '') or '',
        'kind': getattr(channel, 'kind', '') or '',
        'wpm': _as_int(getattr(channel, 'wpm', 158), 158),
        'publish_mode': getattr(channel, 'publish_mode', '') or '',
        'character_design_mode': (
            getattr(channel, 'character_design_mode', '') or ''
        ),
        'branding': branding_vars,
    }


def _resolve_footage_config(channel: Any) -> Any:
    try:
        config = getattr(channel, 'footage_sourcing', None)
    except ObjectDoesNotExist:
        config = None
    if config is not None:
        return config
    helper = getattr(channel, 'footage_sourcing_or_default', None)
    if callable(helper):
        return helper()
    return None


def _footage_dict(channel: Any) -> dict[str, Any]:
    """Expose footage sourcing settings to prompt templates."""
    from server.apps.channels.models import (  # noqa: PLC0415
        DEFAULT_ENABLED_PROVIDERS,
    )

    config = _resolve_footage_config(channel)
    if config is None:
        return {
            'providers': list(DEFAULT_ENABLED_PROVIDERS),
            'sourcing_mode': 'stock_first',
            'ai_fallback_enabled': True,
            'min_width': 1280,
            'attribution_required': True,
        }
    providers = list(getattr(config, 'enabled_providers', []) or [])
    if not providers:
        providers = list(DEFAULT_ENABLED_PROVIDERS)
    return {
        'providers': providers,
        'sourcing_mode': getattr(config, 'sourcing_mode', 'stock_first'),
        'ai_fallback_enabled': bool(
            getattr(config, 'ai_fallback_enabled', True),
        ),
        'min_width': int(getattr(config, 'min_clip_width', 1280)),
        'attribution_required': bool(
            getattr(config, 'require_attribution', True),
        ),
    }


def _default_format(channel: Any) -> dict[str, Any] | None:
    try:
        niche = getattr(channel, 'niche_config', None)
    except ObjectDoesNotExist:
        return None
    if niche is None:
        return None
    fmt = getattr(niche, 'format', None)
    if fmt is None:
        return None
    return _format_dict(fmt)


def _pack_character(char: Any) -> dict[str, Any]:
    return {
        'name': getattr(char, 'name', '') or '',
        'appearance_prompt': getattr(char, 'appearance_prompt', '') or '',
        'persona': getattr(char, 'persona', '') or '',
    }


async def _character_from_cast(run_id: str) -> dict[str, Any] | None:
    try:
        uuid.UUID(run_id)
    except ValueError:
        return None
    from server.apps.pipelines.models import RunCast  # noqa: PLC0415

    row = await (
        RunCast.objects
        .select_related('character')
        .filter(run_id=run_id, role='protagonist')
        .afirst()
    )
    if row is None:
        row = await (
            RunCast.objects
            .select_related('character')
            .filter(run_id=run_id)
            .afirst()
        )
    if row is None:
        return None
    return _pack_character(row.character)


async def _character_from_channel(channel: Any) -> dict[str, Any] | None:
    from server.apps.channels.models import (  # noqa: PLC0415
        Character,
        CharacterStatus,
    )

    channel_id = getattr(channel, 'id', None)
    if channel_id is None:
        return None
    try:
        uuid.UUID(str(channel_id))
    except ValueError:
        return None
    row = await Character.objects.filter(
        channel_id=channel_id,
        status=CharacterStatus.APPROVED,
    ).afirst()
    if row is None:
        return None
    return _pack_character(row)


async def _character_dict(
    run_id: str,
    channel: Any,
) -> dict[str, Any] | None:
    packed = await _character_from_cast(run_id)
    if packed is not None:
        return packed
    return await _character_from_channel(channel)


def _config_seconds(config: Any) -> int | None:
    if not isinstance(config, dict):
        return None
    raw = config.get('total_target_seconds')
    if raw is None:
        return None
    return _as_int(raw, 0)


async def build_prompt_variables(
    ctx: StageContext,
    *,
    extra: dict[str, Any] | None = None,
    include_character: bool = True,
) -> dict[str, Any]:
    """Build the Jinja namespace used by prompt templates."""
    try:
        niche = getattr(ctx.channel, 'niche_config', None)
    except ObjectDoesNotExist:
        niche = None
    wpm = _as_int(getattr(ctx.channel, 'wpm', 158), 158)
    bible = getattr(niche, 'visual_bible', '') if niche else ''
    medium = getattr(niche, 'visual_medium', '') if niche else ''
    raw_negatives = (
        getattr(niche, 'style_negatives', None) if niche else None
    )
    variables: dict[str, Any] = {
        'topic': ctx.run.topic,
        'channel': _channel_dict(ctx.channel),
        'niche': _niche_dict(ctx.channel),
        'lore': getattr(niche, 'lore_document', '') if niche else '',
        'visual_bible': bible if isinstance(bible, str) else '',
        'visual_medium': medium if isinstance(medium, str) else '',
        'style_negatives': (
            list(raw_negatives) if isinstance(raw_negatives, list) else []
        ),
        'format': _default_format(ctx.channel),
        'upstream': ctx.upstream,
        'config': ctx.config,
        'character': None,
        'footage': _footage_dict(ctx.channel),
        'wpm': wpm,
        'total_target_seconds': _config_seconds(ctx.config),
    }
    if include_character:
        variables['character'] = await _character_dict(
            str(ctx.run.id),
            ctx.channel,
        )
    if extra:
        variables.update(extra)
    return variables
