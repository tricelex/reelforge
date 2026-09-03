"""Pydantic AI channel-research agent (not a pipeline stage)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, final

import attrs
import msgspec
from django.conf import settings
from pydantic_ai import Agent, ModelRetry, RunContext, ToolDefinition
from pydantic_ai.models.anthropic import AnthropicModelSettings
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
from server.common.exceptions import FatalProviderError, RetryableProviderError

_MAX_TOKENS = 16384
_SUMMARY_CHARS = 240
_CONTEXT_VIDEOS_PER_LIST = 8

# resolve_channel, list_channel_videos, and (with NexLev) channel_about /
# channel_outliers / similar_channels are NOT agent tools: the model was
# always going to call each of them exactly once, so making it spend a
# full paid LLM turn deciding to do so was pure waste - and because the
# growing conversation is resent in full on every subsequent turn, that
# waste compounded across the whole run. _prefetch_context() fetches all
# of it deterministically before the agent even starts; only tools that
# genuinely need model judgment (which videos/queries are worth a call)
# remain, with tight caps.
TOOL_CAPS: dict[str, int] = {
    'youtube_search': 2,
    'video_info': 3,
    'web_search': 2,
    # DataForSEO-only tools (disabled by default; NexLev is the default
    # provider and never registers these) — kept so trace.consume() has
    # a cap to read if DATAFORSEO_ENABLED is ever turned on.
    'video_comments': 2,
    'video_subtitles': 1,
}
# The three remaining tools cap out at 7 calls total. Leave headroom for
# ModelRetry nudges and the final output turn(s) without coming anywhere
# near the previous 20-plus-call, $7-per-run budget.
_REQUEST_LIMIT = 12

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
Inspect thumbnails and video_info before classifying.

The user message already contains the channel's resolve info, recent AND
popular video lists, about, outliers, and similar channels - this is a
one-time fixed snapshot, not something you can refresh. Do NOT call a
tool to re-fetch any of it; read it directly from the user message.

Use tools with extreme discipline — most runs need only 3-5 tool calls
total, never more. Each call spends real API quota AND a full paid model
turn:
- video_info on the 2-3 strongest videos only, for thumbnails/pacing
  (cap 3)
- youtube_search for competitors/adjacent formats — at most 2 targeted
  queries, only if the provided context doesn't already answer it
- web_search for market/context — at most 2 targeted queries, only if
  genuinely needed
Do not research similar channels further (no video_info or outliers on
them) — they're listed for competitor mapping only.

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


def _hide_when_capped(
    name: str,
) -> Callable[
    [RunContext[ChannelResearchDeps], ToolDefinition],
    ToolDefinition | None,
]:
    """Drop a tool from the model's choices once its cap is used up.

    ToolTrace.consume() bouncing an over-cap call back with ModelRetry
    still puts the tool in front of the model every turn - a confused or
    unlucky model can keep re-offering it (or hop between several capped
    tools) turn after turn, burning the whole request_limit without ever
    reaching final output. Hiding the tool once its cap is spent removes
    that option outright instead of hoping the model takes the hint.
    """

    def prepare(
        ctx: RunContext[ChannelResearchDeps],
        tool_def: ToolDefinition,
    ) -> ToolDefinition | None:
        if ctx.deps.trace.counts.get(name, 0) >= TOOL_CAPS[name]:
            return None
        return tool_def

    return prepare


def _summarize(data: object) -> str:
    text = json.dumps(data, default=str)
    if len(text) <= _SUMMARY_CHARS:
        return text
    return f'{text[: _SUMMARY_CHARS - 3]}...'


def _build_user_prompt(
    deps: ChannelResearchDeps,
    context: dict[str, Any],
) -> str:
    market = deps.target_market or '(omitted - same-niche new brand)'
    working = deps.working_name or '(propose a distinct brandable name)'
    extra = deps.notes or '(none)'
    context_json = json.dumps(context, default=str)
    return (
        f'Research this YouTube channel: {deps.source_channel_url}\n'
        f'Target market: {market}\n'
        f'Working name: {working}\n'
        f'Content kind: {deps.kind}\n'
        f'Operator notes: {extra}\n\n'
        'Already-fetched channel context (resolve info, recent + popular '
        'video lists, about, outliers, similar channels) - do NOT call a '
        f'tool to re-fetch any of this:\n{context_json}\n\n'
        'Pick 2-3 of the strongest videos above and call video_info on '
        'each for thumbnails/pacing. Classify visual_medium from '
        'thumbnails/video_info. Return research_report + channel_spec '
        'that pass the quality bar.'
    )


async def _fetch_optional[T](awaitable: Awaitable[T]) -> T | None:
    """Await a supplementary context fetch.

    A provider miss just means that section is absent, not a reason to
    fail the whole job before the agent even starts.
    """
    try:
        return await awaitable
    except (FatalProviderError, RetryableProviderError):
        return None


async def _prefetch_context(deps: ChannelResearchDeps) -> dict[str, Any]:
    """Fetch the channel's fixed, always-needed context once, up front.

    The model was always going to ask for exactly this - once each - so
    there was never any judgment to spend a paid turn on.
    """
    resolved = await yt_client.resolve_channel(
        deps.source_channel_url,
        deps.youtube_api_key,
    )
    channel_id = str(resolved['id'])
    deps.trace.record('resolve_channel', {}, resolved)

    recent, popular = await asyncio.gather(
        _fetch_optional(
            yt_client.list_channel_videos(
                channel_id,
                deps.youtube_api_key,
                order='date',
                max_results=_CONTEXT_VIDEOS_PER_LIST,
            ),
        ),
        _fetch_optional(
            yt_client.list_channel_videos(
                channel_id,
                deps.youtube_api_key,
                order='viewCount',
                max_results=_CONTEXT_VIDEOS_PER_LIST,
            ),
        ),
    )
    deps.trace.record(
        'list_channel_videos',
        {'channel_id': channel_id, 'order': 'date'},
        recent,
    )
    deps.trace.record(
        'list_channel_videos',
        {'channel_id': channel_id, 'order': 'viewCount'},
        popular,
    )
    context: dict[str, Any] = {
        'channel': resolved,
        'channel_id': channel_id,
        'recent_videos': recent or [],
        'popular_videos': popular or [],
    }
    if settings.NEXLEV_ENABLED:
        await _merge_nexlev_channel_context(channel_id, context)
    return context


async def _merge_nexlev_channel_context(
    channel_id: str,
    context: dict[str, Any],
) -> None:
    """Fetch NexLev's channel-scoped sections and add them to `context`."""
    service = NexLevService()
    about, outliers, similar = await asyncio.gather(
        _fetch_optional(service.get_channel_about(channel_id)),
        _fetch_optional(service.get_channel_outliers(channel_id)),
        _fetch_optional(service.get_similar_channels(channel_id)),
    )
    context['channel_about'] = (
        msgspec.to_builtins(about) if about is not None else None
    )
    context['channel_outliers'] = (
        [msgspec.to_builtins(o) for o in outliers]
        if outliers is not None
        else []
    )
    context['similar_channels'] = (
        [msgspec.to_builtins(s) for s in similar] if similar is not None else []
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
        # ToolTrace.consume() raises ModelRetry for BOTH the intentional
        # "cap reached, use another tool" nudge AND a tool's genuine
        # provider errors (e.g. a video NexLev has no data for) - both
        # share this same per-tool-name retry budget. Too low a number
        # here means one cap nudge plus one real 404 on the same tool
        # (easily happens; not every video is in NexLev) exceeds the
        # budget and pydantic-ai raises UnexpectedModelBehavior, aborting
        # the whole run instead of letting the model route around it.
        retries=5,
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
    """Attach research tools with per-tool caps.

    resolve_channel, list_channel_videos, and NexLev's channel-scoped
    sections are prefetched by `_prefetch_context()` instead of being
    tools - see the TOOL_CAPS comment.
    """
    if settings.DATAFORSEO_ENABLED:
        _register_dataforseo_tools(agent)
    if settings.NEXLEV_ENABLED:
        _register_nexlev_video_tools(agent)
    _register_web_search_tool(agent)


def _register_dataforseo_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach DataForSEO YouTube Live tools."""

    @agent.tool(prepare=_hide_when_capped('youtube_search'))
    async def youtube_search(
        ctx: RunContext[ChannelResearchDeps],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """Search YouTube via DataForSEO for videos and channels.

        Use for competitors and adjacent formats. Cap 2 queries.
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

    @agent.tool(prepare=_hide_when_capped('video_info'))
    async def video_info(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch DataForSEO video metadata for one video_id. Cap 3."""
        ctx.deps.trace.consume('video_info')
        result = await dfs_client.youtube_video_info(
            video_id,
            ctx.deps.dataforseo_login,
            ctx.deps.dataforseo_password,
        )
        ctx.deps.trace.record('video_info', {'video_id': video_id}, result)
        return result

    @agent.tool(prepare=_hide_when_capped('video_comments'))
    async def video_comments(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch comment themes for audience language. Cap 2."""
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

    @agent.tool(prepare=_hide_when_capped('video_subtitles'))
    async def video_subtitles(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch subtitles for pacing/format. Expensive - cap 1."""
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


def _register_nexlev_video_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach NexLev's video-scoped tools (search, info).

    Channel-scoped sections (about, outliers, similar) are prefetched by
    `_merge_nexlev_channel_context()` instead - see the TOOL_CAPS comment.
    """
    service = NexLevService()

    @agent.tool(prepare=_hide_when_capped('youtube_search'))
    async def youtube_search(
        ctx: RunContext[ChannelResearchDeps],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """Search YouTube live via NexLev for videos and channels.

        Use for competitors and adjacent formats. Cap 2 queries.
        """
        ctx.deps.trace.consume('youtube_search')
        items = await service.search_youtube(keyword)
        result = [msgspec.to_builtins(item) for item in items]
        ctx.deps.trace.record('youtube_search', {'keyword': keyword}, result)
        return result

    @agent.tool(prepare=_hide_when_capped('video_info'))
    async def video_info(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> dict[str, Any]:
        """Fetch NexLev video metadata for one video_id. Cap 3."""
        ctx.deps.trace.consume('video_info')
        try:
            details = await service.get_video_details(video_id)
        except FatalProviderError as exc:
            msg = f'No NexLev data for video_id {video_id}: {exc}'
            raise ModelRetry(msg) from exc
        result: dict[str, Any] = msgspec.to_builtins(details)
        ctx.deps.trace.record('video_info', {'video_id': video_id}, result)
        return result


def _register_web_search_tool(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach Exa web_search with the research-stage budget."""

    @agent.tool(prepare=_hide_when_capped('web_search'))
    async def web_search(
        ctx: RunContext[ChannelResearchDeps],
        query: str,
    ) -> list[dict[str, Any]]:
        """Search the web for market context. Cap 2 targeted queries."""
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
    context = await _prefetch_context(deps)
    result = await _agent(to_pydantic_ai_model(model_slug)).run(
        _build_user_prompt(deps, context),
        deps=deps,
        # Cache the (large, static-per-run) system prompt, tool schemas,
        # and growing message history so each of the few remaining turns
        # only pays full price for what's actually new.
        model_settings=AnthropicModelSettings(
            max_tokens=_MAX_TOKENS,
            anthropic_cache_instructions=True,
            anthropic_cache_tool_definitions=True,
            anthropic_cache=True,
        ),
        usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT),
    )
    return result.output, _usage_dict(result, len(deps.trace.entries))
