"""Tests for NexLevService's async channel-analysis job methods."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.nexlev.logic import constants
from server.apps.nexlev.models import NexLevChannelRecord
from server.apps.nexlev.services import NexLevService

_RAW_RESULT = {
    'status': 'completed',
    'result': {
        'strategic_insights': {
            'suggested_topics': {
                'topics': [{'title': 'Topic A', 'description': 'desc'}],
            },
            'script_blueprint': {
                'recommended_stages': [
                    {
                        'stage': 'Hook',
                        'purpose': 'grab attention',
                        'recommended_length_seconds': 30,
                        'winning_formula': 'shocking claim',
                    },
                ],
            },
            'title_format_strategy': {
                'format_groups': [
                    {
                        'format_name': 'X vs Y',
                        'format_description': 'comparison',
                        'video_count': 5,
                    },
                ],
            },
        },
    },
}


@pytest.mark.django_db(transaction=True)
def test_create_channel_analysis_job_returns_job_id() -> None:
    service = NexLevService()

    async def _inner() -> str:
        with patch(
            'server.apps.nexlev.services.nexlev_client'
            '.create_channel_analysis_job',
            new=AsyncMock(return_value='job-1'),
        ):
            return await service.create_channel_analysis_job('UC1')

    assert asyncio.run(_inner()) == 'job-1'


@pytest.mark.django_db(transaction=True)
def test_get_channel_analysis_result_returns_none_while_processing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client'
            '.get_channel_analysis_result',
            new=AsyncMock(return_value=None),
        ):
            return await service.get_channel_analysis_result('job-1', 'UC1')

    assert asyncio.run(_inner()) is None


@pytest.mark.django_db(transaction=True)
def test_get_channel_analysis_result_stores_on_completion() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client'
            '.get_channel_analysis_result',
            new=AsyncMock(return_value=_RAW_RESULT),
        ):
            return await service.get_channel_analysis_result('job-1', 'UC1')

    result = asyncio.run(_inner())
    assert result is not None
    assert result.suggested_topics[0].title == 'Topic A'
    assert result.script_blueprint[0].stage == 'Hook'
    assert result.title_format_groups[0].format_name == 'X vs Y'
    record = NexLevChannelRecord.objects.get(channel_id='UC1')
    assert record.channel_analysis_fetched_at is not None
    assert record.quota_spent == constants.QUOTA_COST_CHANNEL_ANALYSIS_STATUS
