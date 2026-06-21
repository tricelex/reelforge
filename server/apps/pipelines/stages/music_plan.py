"""Music plan stage — LLM selects library tracks per chapter."""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import MusicPlanOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, MusicPlanOutput]:
    """Create and cache the music plan agent on first call."""
    a: Agent[StageContext, MusicPlanOutput] = Agent(
        PYDANTIC_AI_MODEL,
        output_type=MusicPlanOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render('music_plan', {})
        return sys or (
            'You are a music supervisor for documentary videos. '
            'Select one music track per chapter from the provided library. '
            "Match mood to the chapter's retention device and thesis. "
            'Set gain_db relative to -18 LUFS bed target (typically -3 to -6).'
        )

    return a


async def _fetch_music_library(channel_id: str) -> list[dict[str, Any]]:
    """Query LibraryAsset for MUSIC kind, scoped to channel then global."""
    from server.apps.assets.models import (  # noqa: PLC0415
        LibraryAsset,
        LibraryAssetKind,
    )

    channel_qs = LibraryAsset.objects.filter(
        kind=LibraryAssetKind.MUSIC,
        is_active=True,
        channel__id=channel_id,
    )
    global_qs = LibraryAsset.objects.filter(
        kind=LibraryAssetKind.MUSIC,
        is_active=True,
        channel__isnull=True,
    )
    return [
        {
            'id': str(asset.id),
            'name': asset.name,
            'tags': asset.tags,
            'meta': asset.meta,
        }
        async for asset in (channel_qs | global_qs).order_by('name')[:50]
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
        chapters = ctx.upstream.get('outline', {}).get('chapters', [])
        channel_id = str(getattr(ctx.channel, 'id', ''))
        library = await _fetch_music_library(channel_id)
        niche = getattr(ctx.channel, 'niche_config', None)
        mood_map = getattr(niche, 'music_mood_map', {}) if niche else {}

        _, usr = await ctx.prompts.render(
            'music_plan',
            {
                'chapters': chapters,
                'library': library,
                'mood_map': mood_map,
            },
        )
        user_prompt = usr or (
            f'Select music for each chapter:\n'
            f'Chapters: {chapters}\n'
            f'Music library (id, name, tags): {library}\n'
            f'Mood map: {mood_map}\n'
            f'Output one entry per chapter with library_asset_id and gain_db.'
        )
        output: MusicPlanOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )
        return output.model_dump()
