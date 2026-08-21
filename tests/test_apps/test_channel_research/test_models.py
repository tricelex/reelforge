"""Tests for ChannelResearchJob ORM."""

import pytest

from server.apps.channel_research.logic.constants import ChannelResearchKind
from server.apps.channel_research.models import ChannelResearchJob


@pytest.mark.django_db
def test_job_str_prefers_working_name() -> None:
    job = ChannelResearchJob.objects.create(
        source_channel_url='https://www.youtube.com/@HistoryHub',
        working_name='Forge History',
        kind=ChannelResearchKind.LONGFORM,
    )
    assert str(job) == 'Forge History'


@pytest.mark.django_db
def test_job_str_falls_back_to_url() -> None:
    job = ChannelResearchJob.objects.create(
        source_channel_url='https://www.youtube.com/@HistoryHub',
        kind=ChannelResearchKind.LONGFORM,
    )
    assert str(job).startswith('https://www.youtube.com/@HistoryHub')
