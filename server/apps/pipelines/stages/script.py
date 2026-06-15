"""Script stage — full narration script generation."""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.pipelines.schemas import ScriptOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, ScriptOutput]:
    """Create and cache the script agent on first call."""
    a: Agent[StageContext, ScriptOutput] = Agent(
        'anthropic:claude-opus-4-8',
        output_type=ScriptOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render(
            'script', {'topic': ctx.deps.run.topic},
        )
        return sys or (
            'You are a professional documentary script writer. '
            'No greetings. Short sentences. Curiosity gaps at chapter ends. '
            'First 30s hooks must restate the core payoff.'
        )

    return a


@register_stage
class ScriptStage(Stage):
    """Stage 3: full narration script per chapter."""

    key = 'script'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write a full script for all chapters from outline + research."""
        outline = ctx.upstream.get('outline', {})
        research = ctx.upstream.get('research', {})
        chapters = outline.get('chapters', [])
        wpm = getattr(ctx.channel, 'wpm', 158)

        _, usr = await ctx.prompts.render(
            'script',
            {
                'topic': ctx.run.topic,
                'chapters': chapters,
                'research': research,
                'wpm': wpm,
            },
        )
        user_prompt = usr or (
            f'Write the full script for "{ctx.run.topic}".\n'
            f'Chapters: {chapters}\n'
            f'Research: {research.get("brief", {})}\n'
            f'Target WPM: {wpm}. '
            f'Include a closing_line per chapter for continuity.'
        )
        output: ScriptOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )
        return output.model_dump()
