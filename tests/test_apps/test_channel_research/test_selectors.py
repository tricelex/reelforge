"""Selector pagination tests."""

import pytest

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.selectors import get_job, list_jobs


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
