"""Script stage — full narration script generation."""

from functools import lru_cache
from typing import Any, cast, override

from pydantic_ai import Agent, ModelRetry, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.clients.embeddings import embed_text
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.logic.scene_density import coverage_ok
from server.apps.pipelines.logic.similarity import is_too_similar
from server.apps.pipelines.schemas import ScriptOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_SIMILARITY_RETRY_HINT = (
    'Your previous draft was too similar to a recent video on this '
    'channel. Use a different structure, different examples, and '
    'different phrasing throughout.'
)

# A script that collapses into far fewer/more words than the outline calls
# for usually means a prompt asked for the wrong deliverable shape (e.g. one
# monolithic episode instead of one chapter per outline entry) and the model
# produced a stub. Wide band — this only catches catastrophic collapse, not
# ordinary pacing variance.
_MAX_SCRIPT_ATTEMPTS = 3
_COVERAGE_RATIO_MIN = 0.5
_COVERAGE_RATIO_MAX = 2.5


def _expected_word_count(chapters: list[dict[str, Any]], wpm: int) -> int:
    """Estimate total narration words the outline calls for, at wpm."""
    total_seconds = sum(
        float(ch.get('target_seconds', 0) or 0) for ch in chapters
    )
    return round(total_seconds / 60 * wpm)


def _coverage_note(
    output: ScriptOutput,
    outline_chapters: list[dict[str, Any]],
    expected_words: int,
) -> str:
    """Return a corrective hint when the script doesn't cover the outline.

    Empty string means the script is acceptable.
    """
    if not outline_chapters:
        return ''
    if len(output.chapters) != len(outline_chapters):
        return (
            f'You wrote {len(output.chapters)} chapters but the outline '
            f'has {len(outline_chapters)}. Write exactly one script '
            f'chapter per outline chapter, in the same order — do not '
            f'collapse the episode into a single chapter or a summary.'
        )
    if expected_words and not coverage_ok(
        output.total_word_count,
        expected_words,
        _COVERAGE_RATIO_MIN,
        _COVERAGE_RATIO_MAX,
    ):
        return (
            f'You wrote {output.total_word_count} words total but the '
            f'outline calls for roughly {expected_words}. Write full '
            f'spoken narration for every chapter, matching each '
            f"chapter's target_seconds — do not summarize."
        )
    return ''


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, ScriptOutput]:
    """Create and cache the script agent on first call."""
    a: Agent[StageContext, ScriptOutput] = Agent(
        model,
        output_type=ScriptOutput,
        deps_type=StageContext,
        # Default output retries is 1 — too tight for ScriptOutput's
        # commentary-distinct validator + large Anthropic tool payloads.
        retries={'output': 3},
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(ctx.deps)
        sys, _ = await ctx.deps.prompts.render('script', variables)
        return sys or (
            'You are a professional documentary script writer. '
            'No greetings. Short sentences. Curiosity gaps at chapter ends. '
            'First 30s hooks must restate the core payoff.'
        )

    @a.output_validator
    def _validate(  # pragma: no cover
        ctx: RunContext[StageContext],
        output: ScriptOutput,
    ) -> ScriptOutput:
        """Reject scripts whose commentary is filler, not genuine analysis."""
        try:
            output.model_validate(output.model_dump())
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return output

    return a


async def _generate_script(
    ctx: StageContext,
    extra_hint: str = '',
) -> ScriptOutput:
    """Build the script prompt and run the agent, retrying on weak coverage."""
    outline = ctx.upstream.get('outline', {})
    research = ctx.upstream.get('research', {})
    chapters = outline.get('chapters', [])
    wpm = getattr(ctx.channel, 'wpm', 158)
    expected_words = _expected_word_count(chapters, wpm)

    variables = await build_prompt_variables(
        ctx,
        extra={'wpm': wpm},
        include_character=True,
    )
    _, usr = await ctx.prompts.render('script', variables)
    base_user_prompt = usr or (
        f'Write the full script for "{ctx.run.topic}".\n'
        f'Chapters: {chapters}\n'
        f'Research: {research.get("brief", {})}\n'
        f'Target WPM: {wpm}. '
        f'Include a closing_line per chapter for continuity. '
        f'For every chapter also write commentary: 1-3 sentences of '
        f'genuine analysis or a stated opinion — not a restatement of '
        f'the narration — that reflects a real editorial point of view '
        f'on the material.'
    )
    model_slug = await resolve_stage_model(ctx, ScriptStage.key)
    coverage_note = ''
    for _attempt in range(_MAX_SCRIPT_ATTEMPTS):
        user_prompt = base_user_prompt
        if extra_hint:
            user_prompt = f'{user_prompt}\n\n{extra_hint}'
        if coverage_note:
            user_prompt = f'{user_prompt}\n\n{coverage_note}'
        output: ScriptOutput = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key=ScriptStage.key,
            model_slug=model_slug,
            # 1 initial + up to 3 output-validation retries.
            request_limit=5,
        )
        coverage_note = _coverage_note(output, chapters, expected_words)
        if not coverage_note:
            return output
    raise FatalProviderError(
        f'script: {coverage_note}',
        provider='script',
        error_code='script_coverage',
    )


async def _recent_script_embeddings(
    channel_id: str,
    exclude_run_id: str,
    limit: int = 5,
) -> list[list[float]]:
    """script_embedding values from the channel's recent COMPLETED runs."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )

    return [
        cast('list[float]', run.script_embedding)
        async for run in (
            PipelineRun.objects
            .filter(
                channel_id=channel_id,
                status=RunStatus.COMPLETED,
                script_embedding__isnull=False,
            )
            .exclude(id=exclude_run_id)
            .order_by('-finished_at')[:limit]
        )
    ]


@register_stage
class ScriptStage(Stage):
    """Stage 3: full narration script per chapter."""

    key = 'script'
    queue = 'api'
    max_retries = 3
    # Claude multi-chapter tool output can take ~75s/attempt; allow retries.
    timeout_s = 600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write a full script for all chapters from outline + research."""
        output = await _generate_script(ctx)
        combined_text = ' '.join(ch.text for ch in output.chapters)
        new_vec = await embed_text(combined_text)
        recent_vecs = await _recent_script_embeddings(
            str(ctx.channel.id),
            str(ctx.run.id),
        )
        too_similar = is_too_similar(new_vec, recent_vecs)

        if too_similar and getattr(ctx.channel, 'publish_mode', '') == 'auto':
            output = await _generate_script(
                ctx,
                extra_hint=_SIMILARITY_RETRY_HINT,
            )
            combined_text = ' '.join(ch.text for ch in output.chapters)
            new_vec = await embed_text(combined_text)
            too_similar = is_too_similar(new_vec, recent_vecs)

        ctx.run.script_embedding = new_vec
        await ctx.run.asave(update_fields=['script_embedding'])

        result = output.model_dump()
        result['similarity_flag'] = too_similar
        return result
