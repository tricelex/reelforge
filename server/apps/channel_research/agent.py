"""Pydantic AI channel-research agent (not a pipeline stage)."""

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, final

import attrs
import msgspec
from django.conf import settings
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from server.apps.channel_research.logic.schemas import (
    ChannelResearchAgentOutput,
    validate_agent_output,
)
from server.apps.generation.clients import dataforseo as dfs_client
from server.apps.generation.clients import search as search_client
from server.apps.generation.clients import youtube_search as yt_client
from server.apps.generation.logic.model_resolver import (
    resolve_model,
    to_pydantic_ai_model,
)
from server.apps.nexlev.services import NexLevService

_MAX_TOKENS = 16384
_REQUEST_LIMIT = 20
_SUMMARY_CHARS = 240
TOOL_CAPS: dict[str, int] = {
    'resolve_channel': 1,
    'list_channel_videos': 2,
    'youtube_search': 5,
    'video_info': 8,
    'video_comments': 3,
    'video_subtitles': 2,
    'web_search': 4,
    'channel_about': 1,
    'channel_outliers': 1,
    'similar_channels': 1,
}

_SYSTEM_PROMPT = """\
You are a YouTube channel strategist for ReelForge. You research one source
channel with tools, then emit a research dossier AND a ChannelSpec JSON that
an operator can import.

Niche Bending: a hit channel is a MARKET (who watches, what job the video
does) plus a FORMAT (title formula, hook, episode shape) plus a VISUAL
MEDIUM. Steal the proven format; point it at a market. If the operator
supplied a target market, bend the source format into that market
(recommended_mode=bent). If they omitted it, design a NEW channel in the
same niche using the proven format with original branding
(recommended_mode=same_niche) - never a 1:1 clone.

Never copy the source brand name, logo, or channel art. Always include 3-5
niche_bend_opportunities even in same-niche mode.

Research first (tools), then classify:
1. MARKET — who watches, job-to-be-done
2. FORMAT — title formula, hook, episode shape (this is what we bend)
3. visual_medium (required enum, do not guess photoreal): 2d_animation |
   3d_cgi | motion_graphics | photoreal | live_action_stock | mixed
Inspect thumbnails, video_info, and a subtitle sample before classifying.

Use tools with discipline:
- resolve_channel exactly once
- list_channel_videos up to twice (recent + popular)
- channel_about once, for subscriber count and links
- channel_outliers once, for the channel's best-performing videos
- similar_channels once, for competitor/niche mapping
- youtube_search for competitors/adjacent formats (cap 5)
- video_info on the strongest videos (cap 8)
- video_comments sparingly for audience language (cap 3)
- video_subtitles at most twice (expensive; pacing/format only)
- web_search for market/context (cap 4)

Distinctive format or medium (2d_animation, 3d_cgi, motion_graphics,
mixed — anything that is not generic photoreal documentary):
NEVER reuse a shared seed key (factual_documentary, true_crime_case,
educational_explainer, motivational_story, fantasy_lore,
documentary_stock, documentary_archival). Set create_if_missing true,
invent a snake_case key, and emit ALL THREE templates in
prompt_templates with matching prompt_overrides:
- script_<key>: format contract (title energy, hook, POV, sentence
  craft). "Every video is X, never Y."
- visual_prompts_<key>: Flux-ready visual bible ONLY. Jinja uses
  {{ visual_bible }} — never the full lore. Negatives for the wrong
  medium (e.g. photorealistic, live action, 3d render for 2D;
  opposite for photoreal). Shot variety. Freeze character/setting.
- scene_breakdown_<key>: shorter scenes for explainers/animation so
  there are enough stills/cuts
Global visual_prompts stays documentary-photoreal; niche templates
override it via prompt_overrides.

Lore 400-900 words. FIRST section is FORMAT CONTRACT (title formulas,
hook pattern, what every video is) so ideation cannot invent a new show.
Visual identity names the medium in the first sentence. Include Voice,
Sentence craft, World rules, Storytelling, Visual identity, never-do.
Copy the visual lock onto niche: visual_bible (80-160 words, medium in
sentence one), visual_medium, style_tokens, and style_negatives.

config_overrides the agent MUST emit:
- 2d_animation / motion_graphics / 3d_cgi: motion.hero_ratio 0.35-0.50;
  scene_breakdown min_seconds 4-6, max_seconds 8; assembly_style cuts
  8-14/min; image_gen.use_character_ref true if a recurring character
  exists. Do NOT use longform_documentary_v1.
- photoreal / live_action_stock: hero_ratio 0.15-0.25; stock blueprint
  (longform_documentary_v1) only when the source is footage-led.
- mixed: hero_ratio 0.25-0.45 plus the three niche templates.
Recurring character/mascot → character.include + 80-160 word
appearance_prompt (wardrobe, line style, proportions) +
character_design_mode auto.

Seed ideas must obey the bent format (same title formula), not generic
documentary topics. style_tokens and style_negatives on the dossier
AND on channel_spec.niche must match the medium (negatives required
for distinctive media).

Other quality bar:
- music_pool_tags overlap every music_mood_map value
- seed_ideas only when kind is LONGFORM (3-8 strong topics)
- character.include is false iff character_design_mode is none
- default_blueprint_name must be one of: longform_v1,
  longform_documentary_v1, longform_editor_v1, longform_doc_editor_v1,
  shorts_v1, clipping_v1, clipping_v1_manual
- If create_if_missing is false: prompt_templates=[] and
  prompt_overrides={}. Only valid for non-distinctive photoreal
  documentary reuse.
- Empty voice_id ⇒ post_import_notes mention ElevenLabs.

Do not invent infrastructure, OAuth tokens, or a custom blueprint graph.
"""


@final
class ToolTrace:
    """Mutable sink for tool caps and UI chronology."""

    def __init__(self) -> None:
        """Start with an empty trace and zero tool counts."""
        self.entries: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}

    def consume(self, tool: str) -> None:
        """Increment the tool counter or ask the model to stop calling it."""
        cap = TOOL_CAPS[tool]
        used = self.counts.get(tool, 0)
        if used >= cap:
            msg = f'{tool} cap of {cap} reached; use another tool'
            raise ModelRetry(msg)
        self.counts[tool] = used + 1

    def record(self, tool: str, args: dict[str, Any], data: object) -> None:
        """Append a compact trace row for the operator UI."""
        self.entries.append(
            {
                'tool': tool,
                'args': args,
                'summary': _summarize(data),
                'ts': datetime.now(UTC).isoformat(),
            },
        )


@final
@attrs.define(slots=True, frozen=True)
class ChannelResearchDeps:
    """Credentials and trace sink for one research run."""

    job_id: str
    source_channel_url: str
    target_market: str
    working_name: str
    kind: str
    notes: str
    youtube_api_key: str
    dataforseo_login: str
    dataforseo_password: str
    exa_api_key: str
    trace: ToolTrace


def _summarize(data: object) -> str:
    text = json.dumps(data, default=str)
    if len(text) <= _SUMMARY_CHARS:
        return text
    return f'{text[: _SUMMARY_CHARS - 3]}...'


def _build_user_prompt(deps: ChannelResearchDeps) -> str:
    market = deps.target_market or '(omitted - same-niche new brand)'
    working = deps.working_name or '(propose a distinct brandable name)'
    extra = deps.notes or '(none)'
    return (
        f'Research this YouTube channel: {deps.source_channel_url}\n'
        f'Target market: {market}\n'
        f'Working name: {working}\n'
        f'Content kind: {deps.kind}\n'
        f'Operator notes: {extra}\n'
        'Classify visual_medium from thumbnails/video_info/subtitles. '
        'Return research_report + channel_spec that pass the quality bar.'
    )


@lru_cache(maxsize=4)
def _agent(
    model: str,
) -> Agent[ChannelResearchDeps, ChannelResearchAgentOutput]:
    """Create and cache the channel-research agent."""
    a: Agent[ChannelResearchDeps, ChannelResearchAgentOutput] = Agent(
        model,
        output_type=ChannelResearchAgentOutput,
        deps_type=ChannelResearchDeps,
        system_prompt=_SYSTEM_PROMPT,
        retries=2,
    )
    _register_tools(a)

    @a.output_validator
    def _validate_output(
        _ctx: RunContext[ChannelResearchDeps],
        output: ChannelResearchAgentOutput,
    ) -> ChannelResearchAgentOutput:
        try:
            validate_agent_output(output)
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return output

    return a


def _register_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach research tools with per-tool caps."""

    @agent.tool
    async def resolve_channel(
        ctx: RunContext[ChannelResearchDeps],
    ) -> dict[str, Any]:
        """Resolve the source URL to channel snippet, stats, and branding.

        Call exactly once at the start of research.
        """
        ctx.deps.trace.consume('resolve_channel')
        result = await yt_client.resolve_channel(
            ctx.deps.source_channel_url,
            ctx.deps.youtube_api_key,
        )
        ctx.deps.trace.record('resolve_channel', {}, result)
        return result

    @agent.tool
    async def list_channel_videos(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
        order: str = 'date',
    ) -> list[dict[str, Any]]:
        """List recent (`date`) or popular (`viewCount`) videos on a channel.

        Call at most twice - once recent, once popular.
        """
        ctx.deps.trace.consume('list_channel_videos')
        result = await yt_client.list_channel_videos(
            channel_id,
            ctx.deps.youtube_api_key,
            order=order,
        )
        ctx.deps.trace.record(
            'list_channel_videos',
            {'channel_id': channel_id, 'order': order},
            result,
        )
        return result

    if settings.DATAFORSEO_ENABLED:
        _register_dataforseo_tools(agent)
    if settings.NEXLEV_ENABLED:
        _register_nexlev_tools(agent)
    _register_web_search_tool(agent)


def _register_dataforseo_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach DataForSEO YouTube Live tools."""

    @agent.tool
    async def youtube_search(
        ctx: RunContext[ChannelResearchDeps],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """Search YouTube via DataForSEO for videos and channels.

        Use for competitors and adjacent formats. Cap 5 queries.
        """
        ctx.deps.trace.consume('youtube_search')
        result = await dfs_client.youtube_organic_search(
            keyword,
            ctx.deps.dataforseo_login,
            ctx.deps.dataforseo_password,
        )
        ctx.deps.trace.record(
            'youtube_search',
            {'keyword': keyword},
            result,
        )
        return result

    @agent.tool
    async def video_info(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch DataForSEO video metadata for one video_id. Cap 8."""
        ctx.deps.trace.consume('video_info')
        result = await dfs_client.youtube_video_info(
            video_id,
            ctx.deps.dataforseo_login,
            ctx.deps.dataforseo_password,
        )
        ctx.deps.trace.record('video_info', {'video_id': video_id}, result)
        return result

    @agent.tool
    async def video_comments(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch comment themes for audience language. Cap 3."""
        ctx.deps.trace.consume('video_comments')
        result = await dfs_client.youtube_video_comments(
            video_id,
            ctx.deps.dataforseo_login,
            ctx.deps.dataforseo_password,
        )
        ctx.deps.trace.record(
            'video_comments',
            {'video_id': video_id},
            result,
        )
        return result

    @agent.tool
    async def video_subtitles(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch subtitles for pacing/format. Expensive - cap 2."""
        ctx.deps.trace.consume('video_subtitles')
        result = await dfs_client.youtube_video_subtitles(
            video_id,
            ctx.deps.dataforseo_login,
            ctx.deps.dataforseo_password,
        )
        ctx.deps.trace.record(
            'video_subtitles',
            {'video_id': video_id},
            result,
        )
        return result


def _register_nexlev_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach NexLev-backed YouTube data tools (replaces DataForSEO)."""
    _register_nexlev_video_tools(agent)
    _register_nexlev_channel_tools(agent)


def _register_nexlev_video_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach NexLev's video-scoped tools (search, info, comments, subs)."""
    service = NexLevService()

    @agent.tool
    async def youtube_search(
        ctx: RunContext[ChannelResearchDeps],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """Search YouTube live via NexLev for videos and channels.

        Use for competitors and adjacent formats. Cap 5 queries.
        """
        ctx.deps.trace.consume('youtube_search')
        items = await service.search_youtube(keyword)
        result = [msgspec.to_builtins(item) for item in items]
        ctx.deps.trace.record('youtube_search', {'keyword': keyword}, result)
        return result

    @agent.tool
    async def video_info(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> dict[str, Any]:
        """Fetch NexLev video metadata for one video_id. Cap 8."""
        ctx.deps.trace.consume('video_info')
        details = await service.get_video_details(video_id)
        result: dict[str, Any] = msgspec.to_builtins(details)
        ctx.deps.trace.record('video_info', {'video_id': video_id}, result)
        return result

    @agent.tool
    async def video_comments(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch comment themes for audience language. Cap 3."""
        ctx.deps.trace.consume('video_comments')
        comments = await service.get_video_comments(video_id)
        result = [msgspec.to_builtins(c) for c in comments]
        ctx.deps.trace.record(
            'video_comments',
            {'video_id': video_id},
            result,
        )
        return result

    @agent.tool
    async def video_subtitles(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch the transcript for pacing/format. Expensive - cap 2."""
        ctx.deps.trace.consume('video_subtitles')
        segments = await service.get_video_transcript(video_id)
        result = [msgspec.to_builtins(s) for s in segments]
        ctx.deps.trace.record(
            'video_subtitles',
            {'video_id': video_id},
            result,
        )
        return result


def _register_nexlev_channel_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach NexLev's channel-scoped tools (about, outliers, similar)."""
    service = NexLevService()

    @agent.tool
    async def channel_about(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
    ) -> dict[str, Any]:
        """Fetch channel about-info (subs, description, links). Cap 1."""
        ctx.deps.trace.consume('channel_about')
        about = await service.get_channel_about(channel_id)
        result: dict[str, Any] = msgspec.to_builtins(about)
        ctx.deps.trace.record(
            'channel_about',
            {'channel_id': channel_id},
            result,
        )
        return result

    @agent.tool
    async def channel_outliers(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch the channel's highest-performing videos. Cap 1."""
        ctx.deps.trace.consume('channel_outliers')
        outliers = await service.get_channel_outliers(channel_id)
        result = [msgspec.to_builtins(o) for o in outliers]
        ctx.deps.trace.record(
            'channel_outliers',
            {'channel_id': channel_id},
            result,
        )
        return result

    @agent.tool
    async def similar_channels(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch channels similar to this one for competitor mapping. Cap 1."""
        ctx.deps.trace.consume('similar_channels')
        similar = await service.get_similar_channels(channel_id)
        result = [msgspec.to_builtins(s) for s in similar]
        ctx.deps.trace.record(
            'similar_channels',
            {'channel_id': channel_id},
            result,
        )
        return result


def _register_web_search_tool(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach Exa web_search with the research-stage budget."""

    @agent.tool
    async def web_search(
        ctx: RunContext[ChannelResearchDeps],
        query: str,
    ) -> list[dict[str, Any]]:
        """Search the web for market context. Cap 4 targeted queries."""
        ctx.deps.trace.consume('web_search')
        result = await search_client.search(
            query,
            api_key=ctx.deps.exa_api_key,
            num_results=search_client.AGENT_NUM_RESULTS,
            content_mode='highlights',
            max_characters_per_result=(
                search_client.AGENT_MAX_CHARACTERS_PER_RESULT
            ),
            max_total_characters=search_client.AGENT_MAX_TOTAL_CHARACTERS,
        )
        ctx.deps.trace.record('web_search', {'query': query}, result)
        return result


def _usage_dict(result: Any, tool_calls: int) -> dict[str, Any]:
    usage = result.usage
    if callable(usage):
        usage = usage()
    return {
        'input_tokens': getattr(usage, 'input_tokens', 0) or 0,
        'output_tokens': getattr(usage, 'output_tokens', 0) or 0,
        'requests': getattr(usage, 'requests', 0) or 0,
        'tool_calls': tool_calls,
    }


async def run_channel_research_agent(
    deps: ChannelResearchDeps,
) -> tuple[ChannelResearchAgentOutput, dict[str, Any]]:
    """Run the agent and return structured output plus token usage."""
    model_slug = resolve_model('channel_research', None)
    result = await _agent(to_pydantic_ai_model(model_slug)).run(
        _build_user_prompt(deps),
        deps=deps,
        model_settings=ModelSettings(max_tokens=_MAX_TOKENS),
        usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT),
    )
    return result.output, _usage_dict(result, len(deps.trace.entries))
