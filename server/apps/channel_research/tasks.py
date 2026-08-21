"""Background api-queue task for channel research."""

import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings

from server.apps.channel_research.agent import (
    ChannelResearchDeps,
    ToolTrace,
    run_channel_research_agent,
)
from server.apps.channel_research.logic.constants import ChannelResearchStatus
from server.apps.channel_research.logic.schemas import (
    ChannelResearchAgentOutput,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.common.broker import api_broker

logger = structlog.get_logger(__name__)


def _mark_running(job_id: str) -> ChannelResearchJob:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    job.status = ChannelResearchStatus.RUNNING
    job.error_message = ''
    job.save(update_fields=['status', 'error_message', 'updated_at'])
    return job


def _mark_succeeded(
    job_id: str,
    output: ChannelResearchAgentOutput,
    usage: dict[str, Any],
    trace: list[dict[str, Any]],
) -> None:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    source = output.research_report.source_channel
    job.status = ChannelResearchStatus.SUCCEEDED
    job.research_report = output.research_report.model_dump()
    job.channel_spec = output.channel_spec.model_dump()
    job.tool_trace = trace
    job.usage = usage
    job.error_message = ''
    job.source_channel_id = source.channel_id
    job.source_channel_name = source.channel_name
    job.save(
        update_fields=[
            'status',
            'research_report',
            'channel_spec',
            'tool_trace',
            'usage',
            'error_message',
            'source_channel_id',
            'source_channel_name',
            'updated_at',
        ],
    )


def _mark_failed(job_id: str, message: str) -> None:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    job.status = ChannelResearchStatus.FAILED
    job.error_message = message[:2000]
    job.save(update_fields=['status', 'error_message', 'updated_at'])


def _build_deps(job: ChannelResearchJob) -> ChannelResearchDeps:
    return ChannelResearchDeps(
        job_id=str(job.id),
        source_channel_url=job.source_channel_url,
        target_market=job.target_market,
        working_name=job.working_name,
        kind=job.kind,
        notes=job.notes,
        youtube_api_key=str(getattr(settings, 'YOUTUBE_DATA_API_KEY', '')),
        dataforseo_login=str(getattr(settings, 'DATAFORSEO_LOGIN', '')),
        dataforseo_password=str(getattr(settings, 'DATAFORSEO_PASSWORD', '')),
        exa_api_key=str(getattr(settings, 'EXA_API_KEY', '')),
        trace=ToolTrace(),
    )


async def _run_channel_research(job_id: str) -> None:
    job = await sync_to_async(_mark_running)(job_id)
    deps = _build_deps(job)
    try:
        output, usage = await run_channel_research_agent(deps)
        await sync_to_async(_mark_succeeded)(
            job_id,
            output,
            usage,
            deps.trace.entries,
        )
    except Exception as exc:
        logger.exception('channel_research_failed', job_id=job_id)
        await sync_to_async(_mark_failed)(job_id, str(exc))


@api_broker.task(retry_on_error=False)
async def run_channel_research_task(job_id: str) -> None:
    """Run the channel-research agent for one job."""
    await _run_channel_research(job_id)
