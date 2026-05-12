from __future__ import annotations

from pydantic_ai import Agent

from ***REMOVED***.ai.schemas.clipping import ClipAnalysisOutput

clip_analysis_agent: Agent[None, ClipAnalysisOutput] = Agent(
    "anthropic:claude-sonnet-4-5",
    output_type=ClipAnalysisOutput,
    system_prompt=(
        "You are an expert video editor specialising in short-form social media content. "
        "Identify the most engaging segments from the provided transcript. "
        "Return only the structured ClipAnalysisOutput."
    ),
    retries=2,
)
