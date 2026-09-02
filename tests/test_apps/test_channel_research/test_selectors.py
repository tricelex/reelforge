"""Selector pagination tests."""

import pytest

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
    DeepAnalysisStatus,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.selectors import (
    get_job,
    job_to_payload,
    list_jobs,
)
from server.apps.nexlev.logic.value_objects import NexLevChannelAnalysisResult


@pytest.mark.django_db
def test_list_jobs_cursor_and_get() -> None:
    jobs = [
        ChannelResearchJob.objects.create(
            source_channel_url=f'https://www.youtube.com/@Hub{index}',
            working_name=f'Job {index}',
            kind=ChannelResearchKind.LONGFORM,
            status=ChannelResearchStatus.PENDING,
        )
        for index in range(3)
    ]
    page = list_jobs(limit=2)
    assert page.total == 3
    assert len(page.items) == 2
    assert page.next_cursor
    rest = list_jobs(cursor=page.next_cursor, limit=2)
    assert len(rest.items) == 1
    fetched = get_job(str(jobs[0].id))
    assert fetched.working_name == jobs[0].working_name
    assert fetched.channel_spec is None
    assert fetched.research_report is None


@pytest.mark.django_db
def test_job_to_payload_defaults_deep_analysis_to_not_started(
    research_job: ChannelResearchJob,
) -> None:
    payload = job_to_payload(research_job)
    assert payload.deep_analysis_status == DeepAnalysisStatus.NOT_STARTED
    assert payload.deep_analysis_result is None
    assert payload.deep_analysis_job_id == ''
    assert payload.deep_analysis_error_message == ''


@pytest.mark.django_db
def test_job_to_payload_maps_completed_deep_analysis(
    research_job: ChannelResearchJob,
) -> None:
    result = NexLevChannelAnalysisResult(
        suggested_topics=[],
        script_blueprint=[],
        title_format_groups=[],
    )
    research_job.deep_analysis_status = DeepAnalysisStatus.SUCCEEDED
    research_job.deep_analysis_job_id = 'nexlev-job-1'
    research_job.deep_analysis_result = {
        'suggested_topics': [],
        'script_blueprint': [],
        'title_format_groups': [],
    }
    research_job.save()

    payload = job_to_payload(research_job)
    assert payload.deep_analysis_status == DeepAnalysisStatus.SUCCEEDED
    assert payload.deep_analysis_job_id == 'nexlev-job-1'
    assert payload.deep_analysis_result == result
