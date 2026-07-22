"""Async helpers for resolving LLM models inside pipeline stages."""

from typing import TYPE_CHECKING

from server.apps.generation.logic.model_resolver import resolve_model

if TYPE_CHECKING:
    from server.apps.pipelines.stages.base import StageContext


async def resolve_stage_model(ctx: 'StageContext', stage_key: str) -> str:
    """Return the bare model slug for a pipeline stage execution."""
    prompt_model = await ctx.prompts.get_model(stage_key)
    return resolve_model(stage_key, prompt_model)
