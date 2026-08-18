"""Cast proposal stage — refine script cast into RunCast rows."""

from typing import Any, override

from asgiref.sync import sync_to_async

from server.apps.channels.models import (
    Character,
    CharacterOrigin,
    CharacterStatus,
)
from server.apps.pipelines.models import (
    CastDesignStatus,
    CastImportance,
    PipelineRun,
    RunCast,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

_IMPORTANCE_MAP = {
    'main': CastImportance.MAIN,
    'secondary': CastImportance.SECONDARY,
    'background': CastImportance.BACKGROUND,
}


def _normalize_cast(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize cast entries from scene_breakdown output."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item.get('name', '')).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        importance = str(item.get('importance', 'secondary')).lower()
        if importance not in _IMPORTANCE_MAP:
            importance = 'secondary'
        out.append({
            'name': name,
            'role': str(item.get('role', '') or name),
            'importance': importance,
            'appearance_brief': str(item.get('appearance_brief', '')),
        })
    return out


def _cast_from_foreground(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fallback: aggregate unique foreground_cast names as secondary."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for scene in scenes:
        for name_raw in scene.get('foreground_cast') or []:
            name = str(name_raw).strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                'name': name,
                'role': name,
                'importance': 'secondary',
                'appearance_brief': '',
            })
    return out


def _find_library_match(
    channel_id: object,
    name: str,
) -> Character | None:
    """Return an approved channel character with a hero ref, if any."""
    return (
        Character.objects
        .filter(
            channel_id=channel_id,
            name__iexact=name,
            status=CharacterStatus.APPROVED,
            hero_ref__isnull=False,
        )
        .order_by('-updated_at')
        .first()
    )


def _requires_design(cast_rows: list[dict[str, Any]]) -> bool:
    """True when any main/secondary still needs a visual ref."""
    for row in cast_rows:
        if row['importance'] == 'background':
            continue
        if row.get('library_match_id') and row.get('has_hero_ref'):
            continue
        return True
    return False


def _persist_cast_sync(
    run: PipelineRun,
    channel_id: object,
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create Character/RunCast rows (sync ORM)."""
    RunCast.objects.filter(run=run).delete()
    cast_out: list[dict[str, Any]] = []
    for member in members:
        match = _find_library_match(channel_id, member['name'])
        if match is not None:
            character = match
            design_status = CastDesignStatus.APPROVED
            library_match_id = str(match.id)
            has_hero_ref = match.hero_ref_id is not None
        else:
            character = Character.objects.create(
                name=member['name'],
                channel_id=channel_id,
                appearance_prompt=(
                    member['appearance_brief']
                    or f'Character portrait of {member["name"]}'
                ),
                persona='',
                status=CharacterStatus.DRAFT,
                origin=CharacterOrigin.RUN,
                source_run=run,
            )
            design_status = (
                CastDesignStatus.TEXT_ONLY
                if member['importance'] == 'background'
                else CastDesignStatus.PROPOSED
            )
            library_match_id = None
            has_hero_ref = False

        RunCast.objects.create(
            run=run,
            character=character,
            role=member['role'][:60],
            is_ephemeral=library_match_id is None,
            importance=_IMPORTANCE_MAP[member['importance']],
            draft_prompt=(
                member['appearance_brief'] or character.appearance_prompt
            ),
            design_status=design_status,
        )
        cast_out.append({
            'name': member['name'],
            'role': member['role'],
            'importance': member['importance'],
            'draft_prompt': member['appearance_brief'],
            'library_match_id': library_match_id,
            'has_hero_ref': has_hero_ref,
            'character_id': str(character.id),
        })
    return cast_out


@register_stage
class CastProposalStage(Stage):
    """Propose run cast from scene_breakdown and create RunCast rows."""

    key = 'cast_proposal'
    queue = 'api'
    max_retries = 2
    timeout_s = 120

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Create RunCast rows and report whether design is required."""
        breakdown = ctx.upstream.get('scene_breakdown') or {}
        if 'cast' not in breakdown:
            scenes = breakdown.get('scenes') or []
            members = (
                _cast_from_foreground(
                    [s for s in scenes if isinstance(s, dict)],
                )
                if isinstance(scenes, list)
                else []
            )
        else:
            raw_cast = breakdown.get('cast') or []
            if not isinstance(raw_cast, list):
                raw_cast = []
            members = _normalize_cast(
                [m for m in raw_cast if isinstance(m, dict)],
            )

        cast_out = await sync_to_async(_persist_cast_sync)(
            ctx.run,
            ctx.channel.id,
            members,
        )
        requires = _requires_design(cast_out)
        reason = (
            'Main/secondary characters need visual refs'
            if requires
            else 'No main/secondary characters requiring visual refs'
        )
        return {
            'cast': cast_out,
            'requires_character_design': requires,
            'reason': reason,
        }
