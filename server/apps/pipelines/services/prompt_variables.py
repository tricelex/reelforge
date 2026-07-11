"""Jinja2 variable namespace for versioned pipeline prompt templates."""

import uuid
from typing import Any

from server.apps.pipelines.stages.base import StageContext


def _niche_dict(channel: Any) -> dict[str, Any]:
    niche = getattr(channel, 'niche_config', None)
    if niche is None:
        return {
            'audience': '',
            'angle': '',
            'banned_topics': [],
        }
    return {
        'audience': getattr(niche, 'audience', '') or '',
        'angle': getattr(niche, 'angle', '') or '',
        'banned_topics': list(getattr(niche, 'banned_topics', []) or []),
    }


def _format_dict(fmt: Any) -> dict[str, Any]:
    return {
        'name': getattr(fmt, 'name', ''),
        'key': getattr(fmt, 'key', ''),
        'beats': getattr(fmt, 'beats', []),
        'narration_pov': getattr(fmt, 'narration_pov', 'narrator'),
        'music_mood_map': getattr(fmt, 'music_mood_map', {}),
    }


def _channel_dict(channel: Any) -> dict[str, Any]:
    branding = getattr(channel, 'branding', None)
    branding_vars: dict[str, Any] | None = None
    if branding is not None:
        branding_vars = {
            'thumbnail_palette': (
                getattr(branding, 'thumbnail_palette', {}) or {}
            ),
        }
    return {
        'name': getattr(channel, 'name', ''),
        'kind': getattr(channel, 'kind', ''),
        'branding': branding_vars,
    }


def _default_format(channel: Any) -> dict[str, Any] | None:
    niche = getattr(channel, 'niche_config', None)
    if niche is None:
        return None
    fmt = getattr(niche, 'format', None)
    if fmt is None:
        return None
    return _format_dict(fmt)


async def _character_dict(run_id: str) -> dict[str, Any] | None:
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
    char = row.character
    return {
        'name': char.name,
        'appearance_prompt': char.appearance_prompt,
    }


async def build_prompt_variables(
    ctx: StageContext,
    *,
    extra: dict[str, Any] | None = None,
    include_character: bool = True,
) -> dict[str, Any]:
    """Build the standard Jinja namespace documented in pipeline-dag-architecture."""
    niche = getattr(ctx.channel, 'niche_config', None)
    variables: dict[str, Any] = {
        'topic': ctx.run.topic,
        'channel': _channel_dict(ctx.channel),
        'niche': _niche_dict(ctx.channel),
        'lore': getattr(niche, 'lore_document', '') if niche else '',
        'format': _default_format(ctx.channel),
        'upstream': ctx.upstream,
        'config': ctx.config,
        'character': None,
    }
    if include_character:
        variables['character'] = await _character_dict(str(ctx.run.id))
    if extra:
        variables.update(extra)
    return variables
