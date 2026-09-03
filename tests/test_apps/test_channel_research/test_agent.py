"""Tests for channel-research agent helpers."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import override_settings
from pydantic_ai import ModelRetry

from server.apps.channel_research.agent import (
    _SYSTEM_PROMPT,
    ChannelResearchDeps,
    ToolTrace,
    _agent,
    _build_user_prompt,
    _summarize,
    _usage_dict,
    run_channel_research_agent,
)
from server.apps.channel_research.logic.schemas import (
    ChannelResearchAgentOutput,
    validate_agent_output,
)
from server.common.exceptions import FatalProviderError


class _FakeAgent:
    """Stand-in that captures @tool and @output_validator registrations."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.tools: dict[str, Any] = {}
        self.prepares: dict[str, Any] = {}
        self.validator: Any = None

    def tool(self, fn: Any = None, **kwargs: Any) -> Any:
        if fn is not None:
            self.tools[fn.__name__] = fn
            return fn

        def decorator(inner: Any) -> Any:
            self.tools[inner.__name__] = inner
            self.prepares[inner.__name__] = kwargs.get('prepare')
            return inner

        return decorator

    def output_validator(self, fn: Any) -> Any:
        self.validator = fn
        return fn


def _deps() -> ChannelResearchDeps:
    return ChannelResearchDeps(
        job_id='job-1',
        source_channel_url='https://www.youtube.com/@HistoryHub',
        target_market='nurses',
        working_name='Night Shift Lore',
        kind='LONGFORM',
        notes='keep it dry',
        youtube_api_key='yt',
        dataforseo_login='login',
        dataforseo_password='pass',
        exa_api_key='exa',
        trace=ToolTrace(),
    )


def test_tool_trace_enforces_cap() -> None:
    trace = ToolTrace()
    trace.consume('youtube_search')
    trace.consume('youtube_search')
    with pytest.raises(ModelRetry, match='cap of 2'):
        trace.consume('youtube_search')


def test_tool_trace_records_summary_and_ts() -> None:
    trace = ToolTrace()
    trace.record('web_search', {'query': 'rome'}, [{'url': 'https://x'}])
    assert trace.entries[0]['tool'] == 'web_search'
    assert 'rome' in str(trace.entries[0]['args'])
    assert 'ts' in trace.entries[0]


def test_summarize_truncates_long_payloads() -> None:
    blob = {'text': 'x' * 500}
    summary = _summarize(blob)
    assert summary.endswith('...')
    assert len(summary) <= 240


def test_build_user_prompt_includes_inputs() -> None:
    context = {'channel_id': 'UC1', 'recent_videos': [{'id': 'v1'}]}
    prompt = _build_user_prompt(_deps(), context)
    assert '@HistoryHub' in prompt
    assert 'nurses' in prompt
    assert 'Night Shift Lore' in prompt
    assert 'LONGFORM' in prompt
    assert 'visual_medium' in prompt
    assert 'UC1' in prompt
    assert 're-fetch' in prompt


def test_system_prompt_locks_visual_medium_and_templates() -> None:
    assert 'visual_medium' in _SYSTEM_PROMPT
    assert 'script_<key>' in _SYSTEM_PROMPT
    assert 'visual_prompts_<key>' in _SYSTEM_PROMPT
    assert '{{ visual_bible }}' in _SYSTEM_PROMPT
    assert 'scene_breakdown_<key>' in _SYSTEM_PROMPT
    assert 'FORMAT CONTRACT' in _SYSTEM_PROMPT
    assert 'Prefer an existing story_format.key' not in _SYSTEM_PROMPT


def test_build_user_prompt_omitted_market() -> None:
    deps = ChannelResearchDeps(
        job_id='job-1',
        source_channel_url='https://www.youtube.com/@HistoryHub',
        target_market='',
        working_name='',
        kind='LONGFORM',
        notes='',
        youtube_api_key='yt',
        dataforseo_login='login',
        dataforseo_password='pass',
        exa_api_key='exa',
        trace=ToolTrace(),
    )
    prompt = _build_user_prompt(deps, {})
    assert 'omitted' in prompt
    assert 'propose' in prompt


def test_usage_dict_supports_callable_usage() -> None:
    usage_obj = MagicMock(input_tokens=3, output_tokens=4, requests=2)
    result = MagicMock(usage=lambda: usage_obj)
    payload = _usage_dict(result, tool_calls=5)
    assert payload['input_tokens'] == 3
    assert payload['tool_calls'] == 5


def test_run_channel_research_agent_returns_output(
    agent_output: ChannelResearchAgentOutput,
) -> None:
    expected = agent_output
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = expected
    mock_result.usage = SimpleNamespace(
        input_tokens=1,
        output_tokens=2,
        requests=1,
    )
    mock_agent.run = AsyncMock(return_value=mock_result)

    async def _inner() -> object:
        with (
            patch(
                'server.apps.channel_research.agent._agent',
                return_value=mock_agent,
            ),
            patch(
                'server.apps.channel_research.agent._prefetch_context',
                new=AsyncMock(return_value={}),
            ),
        ):
            return await run_channel_research_agent(_deps())

    output, usage = asyncio.run(_inner())
    assert output == expected
    validate_agent_output(output)
    assert usage['input_tokens'] == 1
    mock_agent.run.assert_awaited_once()


@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)
def test_agent_registers_tools_and_validates_output(
    agent_output: ChannelResearchAgentOutput,
) -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-model')
    assert isinstance(fake, _FakeAgent)
    expected_tools = {
        'youtube_search',
        'video_info',
        'video_comments',
        'video_subtitles',
        'web_search',
    }
    assert expected_tools <= set(fake.tools)
    assert 'resolve_channel' not in fake.tools
    assert 'list_channel_videos' not in fake.tools
    ctx = SimpleNamespace(deps=_deps())
    assert fake.validator(ctx, agent_output) is agent_output
    copied = agent_output.model_copy(deep=True)
    copied.channel_spec.channel.name = (
        copied.research_report.source_channel.channel_name
    )
    with pytest.raises(ModelRetry, match='brand name'):
        fake.validator(ctx, copied)


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=False)
def test_dataforseo_tools_not_registered_when_disabled() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-flags-off')
    assert 'youtube_search' not in fake.tools
    assert 'video_info' not in fake.tools
    assert 'video_comments' not in fake.tools
    assert 'video_subtitles' not in fake.tools


@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)
def test_dataforseo_tools_registered_when_enabled() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-flags-on')
    assert 'youtube_search' in fake.tools
    assert 'video_info' in fake.tools


@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)
def test_registered_tools_call_provider_clients() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-tools')
    assert isinstance(fake, _FakeAgent)
    ctx = SimpleNamespace(deps=_deps())

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.channel_research.agent.dfs_client.youtube_organic_search',
                new=AsyncMock(return_value=[{'title': 'hit'}]),
            ),
            patch(
                'server.apps.channel_research.agent.dfs_client.youtube_video_info',
                new=AsyncMock(return_value=[{'video_id': 'v1'}]),
            ),
            patch(
                'server.apps.channel_research.agent.dfs_client.youtube_video_comments',
                new=AsyncMock(return_value=[{'text': 'wow'}]),
            ),
            patch(
                'server.apps.channel_research.agent.dfs_client.youtube_video_subtitles',
                new=AsyncMock(return_value=[{'text': 'hello'}]),
            ),
            patch(
                'server.apps.channel_research.agent.search_client.search',
                new=AsyncMock(return_value=[{'url': 'https://x'}]),
            ),
        ):
            search = await fake.tools['youtube_search'](ctx, keyword='rome')
            info = await fake.tools['video_info'](ctx, video_id='v1')
            comments = await fake.tools['video_comments'](ctx, video_id='v1')
            subs = await fake.tools['video_subtitles'](ctx, video_id='v1')
            web = await fake.tools['web_search'](ctx, query='market')
            return {
                'search': search,
                'info': info,
                'comments': comments,
                'subs': subs,
                'web': web,
            }

    results = asyncio.run(_inner())
    assert results['search'][0]['title'] == 'hit'
    assert results['info'][0]['video_id'] == 'v1'
    assert results['comments'][0]['text'] == 'wow'
    assert results['subs'][0]['text'] == 'hello'
    assert results['web'][0]['url'] == 'https://x'
    assert len(ctx.deps.trace.entries) == 5


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_nexlev_tools_registered_when_enabled() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-nexlev-on')
    expected = {'youtube_search', 'video_info'}
    assert expected <= set(fake.tools)
    assert 'video_comments' not in fake.tools
    assert 'video_subtitles' not in fake.tools
    assert 'channel_about' not in fake.tools
    assert 'channel_outliers' not in fake.tools
    assert 'similar_channels' not in fake.tools


def test_hide_when_capped_removes_tool_once_cap_is_spent() -> None:
    """A capped-out tool must disappear from the model's choices outright.

    Bouncing an over-cap call back with ModelRetry still leaves the tool
    in front of the model every turn - it (or another capped tool) can
    keep getting re-offered and re-declined turn after turn until the
    whole request_limit is spent with no final output. Hiding the tool
    once its cap is spent removes that option instead of hoping the
    model takes the hint.
    """
    from server.apps.channel_research.agent import _hide_when_capped

    prepare = _hide_when_capped('youtube_search')
    ctx = SimpleNamespace(deps=_deps())
    tool_def = SimpleNamespace(name='youtube_search')

    under_cap = prepare(ctx, tool_def)
    ctx.deps.trace.counts['youtube_search'] = 2
    at_cap = prepare(ctx, tool_def)

    assert under_cap is tool_def
    assert at_cap is None


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_nexlev_tools_wired_with_cap_prepare_hooks() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-nexlev-prepare')
    assert fake.prepares['youtube_search'] is not None
    assert fake.prepares['video_info'] is not None


@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)
def test_dataforseo_tools_wired_with_cap_prepare_hooks() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-dataforseo-prepare')
    for name in (
        'youtube_search',
        'video_info',
        'video_comments',
        'video_subtitles',
        'web_search',
    ):
        assert fake.prepares[name] is not None


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_nexlev_tools_call_service_and_record_trace() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-nexlev-tools')
    ctx = SimpleNamespace(deps=_deps())

    from server.apps.nexlev.logic.value_objects import (
        NexLevSearchResultItem,
        NexLevVideoDetails,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.search_youtube',
                new=AsyncMock(
                    return_value=[
                        NexLevSearchResultItem(type='video', title='hit'),
                    ],
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_video_details',
                new=AsyncMock(
                    return_value=NexLevVideoDetails(id='v1', title='X'),
                ),
            ),
        ):
            search = await fake.tools['youtube_search'](ctx, keyword='rome')
            info = await fake.tools['video_info'](ctx, video_id='v1')
            return {'search': search, 'info': info}

    results = asyncio.run(_inner())
    assert results['search'][0]['title'] == 'hit'
    assert results['info']['id'] == 'v1'
    assert len(ctx.deps.trace.entries) == 2


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_merge_nexlev_channel_context_fills_sections() -> None:
    """The channel-scoped NexLev sections come from a prefetch, not tools."""
    from server.apps.channel_research.agent import (
        _merge_nexlev_channel_context,
    )
    from server.apps.nexlev.logic.value_objects import (
        NexLevChannelAbout,
        NexLevOutlierVideo,
        NexLevSimilarChannel,
    )

    async def _inner() -> dict[str, Any]:
        context: dict[str, Any] = {}
        with (
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_channel_about',
                new=AsyncMock(
                    return_value=NexLevChannelAbout(
                        channel_id='UC1',
                        title='X',
                    ),
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_channel_outliers',
                new=AsyncMock(
                    return_value=[
                        NexLevOutlierVideo(video_id='v1', title='Hit'),
                    ],
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_similar_channels',
                new=AsyncMock(
                    return_value=[
                        NexLevSimilarChannel(
                            channel_id='UC2',
                            channel_name='Rival',
                        ),
                    ],
                ),
            ),
        ):
            await _merge_nexlev_channel_context('UC1', context)
        return context

    context = asyncio.run(_inner())
    assert context['channel_about']['channelId'] == 'UC1'
    assert context['channel_outliers'][0]['videoId'] == 'v1'
    assert context['similar_channels'][0]['channelId'] == 'UC2'


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_merge_nexlev_channel_context_tolerates_provider_miss() -> None:
    """A missing NexLev section degrades to empty/None, not a crash."""
    from server.apps.channel_research.agent import (
        _merge_nexlev_channel_context,
    )

    not_found = FatalProviderError(
        'NexLev has no data',
        provider='nexlev',
        error_code='404',
    )

    async def _inner() -> dict[str, Any]:
        context: dict[str, Any] = {}
        with (
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_channel_about',
                new=AsyncMock(side_effect=not_found),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_channel_outliers',
                new=AsyncMock(side_effect=not_found),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_similar_channels',
                new=AsyncMock(side_effect=not_found),
            ),
        ):
            await _merge_nexlev_channel_context('UC1', context)
        return context

    context = asyncio.run(_inner())
    assert context['channel_about'] is None
    assert context['channel_outliers'] == []
    assert context['similar_channels'] == []


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_prefetch_context_gathers_channel_and_videos() -> None:
    from server.apps.channel_research.agent import _prefetch_context

    async def _inner() -> dict[str, Any]:
        with (
            patch(
                'server.apps.channel_research.agent.yt_client.resolve_channel',
                new=AsyncMock(return_value={'id': 'UC1', 'snippet': {}}),
            ),
            patch(
                'server.apps.channel_research.agent.yt_client'
                '.list_channel_videos',
                new=AsyncMock(return_value=[{'id': 'v1'}]),
            ),
            patch(
                'server.apps.channel_research.agent'
                '._merge_nexlev_channel_context',
                new=AsyncMock(),
            ),
        ):
            return await _prefetch_context(_deps())

    context = asyncio.run(_inner())
    assert context['channel_id'] == 'UC1'
    assert context['recent_videos'] == [{'id': 'v1'}]
    assert context['popular_videos'] == [{'id': 'v1'}]


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_prefetch_context_tolerates_missing_video_lists() -> None:
    """A YouTube Data API miss on the video lists degrades gracefully."""
    from server.apps.channel_research.agent import _prefetch_context

    quota_error = FatalProviderError(
        'quota exceeded',
        provider='youtube_search',
    )

    async def _inner() -> dict[str, Any]:
        with (
            patch(
                'server.apps.channel_research.agent.yt_client.resolve_channel',
                new=AsyncMock(return_value={'id': 'UC1'}),
            ),
            patch(
                'server.apps.channel_research.agent.yt_client'
                '.list_channel_videos',
                new=AsyncMock(side_effect=quota_error),
            ),
            patch(
                'server.apps.channel_research.agent'
                '._merge_nexlev_channel_context',
                new=AsyncMock(),
            ),
        ):
            return await _prefetch_context(_deps())

    context = asyncio.run(_inner())
    assert context['recent_videos'] == []
    assert context['popular_videos'] == []


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_video_info_retries_model_when_video_has_no_data() -> None:
    """A single missing video_id should not crash the whole research run."""
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-nexlev-video-not-found')
    ctx = SimpleNamespace(deps=_deps())

    async def _inner() -> None:
        with patch(
            'server.apps.channel_research.agent.NexLevService'
            '.get_video_details',
            new=AsyncMock(
                side_effect=FatalProviderError(
                    'NexLev has no data for video missing-video',
                    provider='nexlev',
                    error_code='404',
                ),
            ),
        ):
            await fake.tools['video_info'](ctx, video_id='missing-video')

    with pytest.raises(ModelRetry):
        asyncio.run(_inner())


def test_agent_retry_budget_absorbs_cap_and_provider_error_nudges() -> None:
    """Cap nudges and NexLev misses share a tool's retry budget.

    Too low a budget turns a couple of expected soft nudges into a hard
    UnexpectedModelBehavior that kills the whole run.
    """
    _agent.cache_clear()
    mock_agent_cls = MagicMock()
    with patch('server.apps.channel_research.agent.Agent', mock_agent_cls):
        _agent('unit-test-retries-budget')
    _, kwargs = mock_agent_cls.call_args
    assert kwargs['retries'] >= 4
