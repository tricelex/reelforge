"""Music plan stage — LLM selects library tracks per chapter."""

from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.schemas import MusicPlanOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError


async def _music_plan_variables(
    ctx: StageContext,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the music library and build prompt variables for music_plan."""
    channel_id = str(getattr(ctx.channel, 'id', ''))
    library = await _fetch_music_library(channel_id)
    niche = getattr(ctx.channel, 'niche_config', None)
    mood_map = getattr(niche, 'music_mood_map', {}) if niche else {}
    variables = await build_prompt_variables(
        ctx,
        extra={
            'library_tracks': library,
            'mood_map': mood_map,
        },
        include_character=False,
    )
    return library, variables


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, MusicPlanOutput]:
    """Create and cache the music plan agent on first call."""
    a: Agent[StageContext, MusicPlanOutput] = Agent(
        model,
        output_type=MusicPlanOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        _, variables = await _music_plan_variables(ctx.deps)
        sys, _ = await ctx.deps.prompts.render('music_plan', variables)
        return sys or (
            'You are a music supervisor for documentary videos. '
            'Select one music track per chapter from the provided library. '
            "Match mood to the chapter's retention device and thesis. "
            'Set gain_db relative to -18 LUFS bed target (typically -3 to -6).'
        )

    return a


async def _fetch_music_library(channel_id: str) -> list[dict[str, Any]]:
    """Query LibraryAsset MUSIC with a verified license, channel then global."""
    from django.db import models  # noqa: PLC0415

    from server.apps.assets.models import (  # noqa: PLC0415
        LibraryAsset,
        LibraryAssetKind,
        LibraryAssetLicense,
    )

    licensed = ~models.Q(license_type=LibraryAssetLicense.UNSPECIFIED)
    global_qs = LibraryAsset.objects.filter(
        licensed,
        kind=LibraryAssetKind.MUSIC,
        is_active=True,
        channel__isnull=True,
    )
    if channel_id:
        channel_qs = LibraryAsset.objects.filter(
            licensed,
            kind=LibraryAssetKind.MUSIC,
            is_active=True,
            channel__id=channel_id,
        )
        combined = channel_qs | global_qs
    else:
        combined = global_qs
    return [
        {
            'id': str(asset.id),
            'name': asset.name,
            'tags': asset.tags,
            'meta': asset.meta,
        }
        async for asset in combined.order_by('name')[:50]
    ]


@register_stage
class MusicPlanStage(Stage):
    """Stage 10: select music tracks per chapter from library."""

    key = 'music_plan'
    queue = 'api'
    max_retries = 3
    timeout_s = 120

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Ask the LLM to pick library music for each chapter."""
        library, variables = await _music_plan_variables(ctx)
        if not library:
            raise FatalProviderError(
                'No licensed music library assets available for this channel',
                provider='music_plan',
                error_code='empty_music_library',
            )

        chapters = ctx.upstream.get('outline', {}).get('chapters', [])
        niche = getattr(ctx.channel, 'niche_config', None)
        mood_map = getattr(niche, 'music_mood_map', {}) if niche else {}

        _, usr = await ctx.prompts.render('music_plan', variables)
        user_prompt = usr or (
            f'Select music for each chapter:\n'
            f'Chapters: {chapters}\n'
            f'Music library (id, name, tags): {library}\n'
            f'Mood map: {mood_map}\n'
            f'Output one entry per chapter with library_asset_id and gain_db.'
        )
        model_slug = await resolve_stage_model(ctx, self.key)
        output: MusicPlanOutput = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key=self.key,
            model_slug=model_slug,
        )
        return output.model_dump()
