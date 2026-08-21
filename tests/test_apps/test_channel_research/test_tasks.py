"""Tests for the channel-research TaskIQ runner."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.channel_research.logic.constants import ChannelResearchStatus
from server.apps.channel_research.logic.schemas import (
    ChannelResearchAgentOutput,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.tasks import (
    _build_deps,
    _mark_failed,
    _mark_running,
    _mark_succeeded,
    _run_channel_research,
    run_channel_research_task,
)


@pytest.mark.django_db
def test_mark_succeeded_persists_outputs(
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
) -> None:
    _mark_succeeded(
        str(research_job.id),
        agent_output,
        {'input_tokens': 10, 'output_tokens': 20, 'tool_calls': 3},
        [{'tool': 'resolve_channel'}],
    )
    research_job.refresh_from_db()
    assert research_job.status == ChannelResearchStatus.SUCCEEDED
    assert research_job.channel_spec['channel']['name'] == 'Forge History'
    assert research_job.source_channel_name == 'Source Hub'
    assert research_job.usage['input_tokens'] == 10
    assert research_job.tool_trace[0]['tool'] == 'resolve_channel'
    assert research_job.error_message == ''


@pytest.mark.django_db
def test_mark_failed_persists_error(
    research_job: ChannelResearchJob,
) -> None:
    _mark_failed(str(research_job.id), 'provider down')
    research_job.refresh_from_db()
    assert research_job.status == ChannelResearchStatus.FAILED
    assert 'provider down' in research_job.error_message


@pytest.mark.django_db
def test_task_delegates_to_runner() -> None:
    with patch(
        'server.apps.channel_research.tasks._run_channel_research',
        new=AsyncMock(),
    ) as mock_run:
        asyncio.run(run_channel_research_task('job-id'))
    mock_run.assert_awaited_once_with('job-id')


@pytest.mark.django_db
def test_mark_running_clears_error(
    research_job: ChannelResearchJob,
) -> None:
    research_job.error_message = 'stale'
    research_job.save(update_fields=['error_message'])
    running = _mark_running(str(research_job.id))
    assert running.status == ChannelResearchStatus.RUNNING
    research_job.refresh_from_db()
    assert research_job.status == ChannelResearchStatus.RUNNING
    assert research_job.error_message == ''


@pytest.mark.django_db
def test_build_deps_copies_job_fields(
    research_job: ChannelResearchJob,
) -> None:
    research_job.target_market = 'nurses'
    research_job.notes = 'keep it dry'
    research_job.save(update_fields=['target_market', 'notes'])
    deps = _build_deps(research_job)
    assert deps.job_id == str(research_job.id)
    assert deps.source_channel_url == research_job.source_channel_url
    assert deps.target_market == 'nurses'
    assert deps.kind == research_job.kind
    assert deps.notes == 'keep it dry'


@pytest.mark.django_db
def test_run_channel_research_success_marks_succeeded(
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
) -> None:
    usage = {'input_tokens': 4, 'output_tokens': 8, 'requests': 2}
    job_id = str(research_job.id)
    with (
        patch(
            'server.apps.channel_research.tasks._mark_running',
            return_value=research_job,
        ) as mock_running,
        patch(
            'server.apps.channel_research.tasks.run_channel_research_agent',
            new=AsyncMock(return_value=(agent_output, usage)),
        ),
        patch(
            'server.apps.channel_research.tasks._mark_succeeded',
        ) as mock_ok,
    ):
        asyncio.run(_run_channel_research(job_id))
    mock_running.assert_called_once_with(job_id)
    mock_ok.assert_called_once()
    assert mock_ok.call_args.args[0] == job_id
    assert mock_ok.call_args.args[1] is agent_output


@pytest.mark.django_db
def test_run_channel_research_failure_marks_failed(
    research_job: ChannelResearchJob,
) -> None:
    job_id = str(research_job.id)
    with (
        patch(
            'server.apps.channel_research.tasks._mark_running',
            return_value=research_job,
        ),
        patch(
            'server.apps.channel_research.tasks.run_channel_research_agent',
            new=AsyncMock(side_effect=RuntimeError('provider down')),
        ),
        patch(
            'server.apps.channel_research.tasks._mark_failed',
        ) as mock_fail,
    ):
        asyncio.run(_run_channel_research(job_id))
    mock_fail.assert_called_once_with(job_id, 'provider down')
