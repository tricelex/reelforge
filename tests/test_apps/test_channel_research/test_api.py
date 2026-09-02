"""DMR API tests for channel research jobs."""

from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channel_research.logic.constants import (
    ChannelResearchStatus,
    DeepAnalysisStatus,
)
from server.apps.channel_research.logic.schemas import (
    ChannelResearchAgentOutput,
)
from server.apps.channel_research.models import ChannelResearchJob


@pytest.mark.django_db(transaction=True)
def test_create_and_get_job(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    with patch('server.apps.channel_research.services.kiq_task'):
        created = dmr_client.post(
            reverse('api:channel_research_api:job-collection'),
            data={
                'source_channel_url': 'https://www.youtube.com/@HistoryHub',
                'working_name': 'Forge History',
                'kind': 'LONGFORM',
            },
            headers=auth_headers,
        )
    assert created.status_code == HTTPStatus.CREATED
    body = created.json()
    assert body['status'] == ChannelResearchStatus.QUEUED
    assert body['working_name'] == 'Forge History'
    assert body['source_channel_url'].endswith('@HistoryHub')
    assert body['channel_spec'] is None
    assert body['research_report'] is None

    detail = dmr_client.get(
        reverse(
            'api:channel_research_api:job-detail',
            kwargs={'job_id': body['id']},
        ),
        headers=auth_headers,
    )
    assert detail.status_code == HTTPStatus.OK
    assert detail.json()['id'] == body['id']


@pytest.mark.django_db(transaction=True)
def test_list_jobs_filters_status(
    dmr_client: DMRClient,
    research_job: ChannelResearchJob,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse('api:channel_research_api:job-collection'),
        query_params={'status': ChannelResearchStatus.PENDING},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 1
    assert response.json()['items'][0]['id'] == str(research_job.id)
    assert response.json()['items'][0]['channel_spec'] is None


@pytest.mark.django_db(transaction=True)
def test_patch_spec_when_succeeded(
    dmr_client: DMRClient,
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
    auth_headers: dict[str, str],
) -> None:
    spec = agent_output.channel_spec.model_dump()
    spec['channel']['name'] = 'Edited'
    research_job.status = ChannelResearchStatus.SUCCEEDED
    research_job.research_report = agent_output.research_report.model_dump()
    research_job.channel_spec = agent_output.channel_spec.model_dump()
    research_job.save()
    response = dmr_client.patch(
        reverse(
            'api:channel_research_api:job-detail',
            kwargs={'job_id': research_job.id},
        ),
        data={'channel_spec': spec},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['channel_spec']['channel']['name'] == 'Edited'


@pytest.mark.django_db(transaction=True)
def test_patch_spec_when_pending_returns_422(
    dmr_client: DMRClient,
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.patch(
        reverse(
            'api:channel_research_api:job-detail',
            kwargs={'job_id': research_job.id},
        ),
        data={'channel_spec': agent_output.channel_spec.model_dump()},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_retry_failed_job(
    dmr_client: DMRClient,
    research_job: ChannelResearchJob,
    auth_headers: dict[str, str],
) -> None:
    research_job.status = ChannelResearchStatus.FAILED
    research_job.error_message = 'provider down'
    research_job.save()
    with patch('server.apps.channel_research.services.kiq_task'):
        response = dmr_client.post(
            reverse(
                'api:channel_research_api:job-retry',
                kwargs={'job_id': research_job.id},
            ),
            headers=auth_headers,
        )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['status'] == ChannelResearchStatus.QUEUED
    assert response.json()['error_message'] == ''


@pytest.mark.django_db(transaction=True)
def test_retry_running_job_returns_422(
    dmr_client: DMRClient,
    research_job: ChannelResearchJob,
    auth_headers: dict[str, str],
) -> None:
    research_job.status = ChannelResearchStatus.RUNNING
    research_job.save(update_fields=['status'])
    response = dmr_client.post(
        reverse(
            'api:channel_research_api:job-retry',
            kwargs={'job_id': research_job.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_create_rejects_non_youtube(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:channel_research_api:job-collection'),
        data={'source_channel_url': 'https://example.com/not-yt'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_detail_unknown_job_returns_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    missing = '00000000-0000-0000-0000-000000000001'
    response = dmr_client.get(
        reverse(
            'api:channel_research_api:job-detail',
            kwargs={'job_id': missing},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db(transaction=True)
def test_list_cursor_pagination(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    with patch('server.apps.channel_research.services.kiq_task'):
        for index in range(3):
            dmr_client.post(
                reverse('api:channel_research_api:job-collection'),
                data={
                    'source_channel_url': (
                        f'https://www.youtube.com/@Hub{index}'
                    ),
                    'working_name': f'Job {index}',
                },
                headers=auth_headers,
            )
    first = dmr_client.get(
        reverse('api:channel_research_api:job-collection'),
        query_params={'limit': '2'},
        headers=auth_headers,
    )
    assert first.status_code == HTTPStatus.OK
    body = first.json()
    assert len(body['items']) == 2
    assert body['next_cursor']
    second = dmr_client.get(
        reverse('api:channel_research_api:job-collection'),
        query_params={'limit': '2', 'cursor': body['next_cursor']},
        headers=auth_headers,
    )
    assert second.status_code == HTTPStatus.OK
    assert len(second.json()['items']) == 1


@pytest.mark.django_db(transaction=True)
def test_patch_spec_rejects_invalid_spec(
    dmr_client: DMRClient,
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
    auth_headers: dict[str, str],
) -> None:
    spec = agent_output.channel_spec.model_dump()
    spec['niche']['lore_document'] = 'Too short. We never do this.'
    research_job.status = ChannelResearchStatus.SUCCEEDED
    research_job.research_report = agent_output.research_report.model_dump()
    research_job.save()
    response = dmr_client.patch(
        reverse(
            'api:channel_research_api:job-detail',
            kwargs={'job_id': research_job.id},
        ),
        data={'channel_spec': spec},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_validate_spec_accepts_quality_bar(
    dmr_client: DMRClient,
    agent_output: ChannelResearchAgentOutput,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:channel_research_api:validate-spec'),
        data=agent_output.channel_spec.model_dump(),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['ok'] is True
    assert body['errors'] == []


@pytest.mark.django_db(transaction=True)
def test_validate_spec_returns_errors_for_short_lore(
    dmr_client: DMRClient,
    agent_output: ChannelResearchAgentOutput,
    auth_headers: dict[str, str],
) -> None:
    spec = agent_output.channel_spec.model_dump()
    spec['niche']['lore_document'] = 'Too short. We never do this.'
    response = dmr_client.post(
        reverse('api:channel_research_api:validate-spec'),
        data=spec,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['ok'] is False
    assert body['errors']


@pytest.mark.django_db(transaction=True)
def test_deep_analysis_endpoint_requires_source_channel_id(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
    research_job: ChannelResearchJob,
) -> None:
    url = reverse(
        'api:channel_research_api:job-deep-analysis',
        kwargs={'job_id': research_job.id},
    )
    response = dmr_client.post(url, headers=auth_headers)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_deep_analysis_endpoint_enqueues_when_channel_id_present(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
    research_job: ChannelResearchJob,
) -> None:
    research_job.source_channel_id = 'UC1'
    research_job.save(update_fields=['source_channel_id'])
    url = reverse(
        'api:channel_research_api:job-deep-analysis',
        kwargs={'job_id': research_job.id},
    )
    with patch('server.apps.channel_research.services.kiq_task'):
        response = dmr_client.post(url, headers=auth_headers)
    assert response.status_code == HTTPStatus.OK
    assert response.json()['deep_analysis_status'] == DeepAnalysisStatus.RUNNING


@pytest.mark.django_db(transaction=True)
def test_apply_suggested_topics_endpoint_requires_completed_deep_analysis(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
    research_job: ChannelResearchJob,
) -> None:
    url = reverse(
        'api:channel_research_api:job-apply-suggested-topics',
        kwargs={'job_id': research_job.id},
    )
    response = dmr_client.post(url, headers=auth_headers)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_apply_suggested_topics_endpoint_merges_topics(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
) -> None:
    research_job.status = ChannelResearchStatus.SUCCEEDED
    research_job.channel_spec = agent_output.channel_spec.model_dump()
    research_job.deep_analysis_status = DeepAnalysisStatus.SUCCEEDED
    research_job.deep_analysis_result = {
        'suggested_topics': [
            {'title': 'New Idea', 'description': 'new topic'},
        ],
        'script_blueprint': [],
        'title_format_groups': [],
    }
    research_job.save()
    url = reverse(
        'api:channel_research_api:job-apply-suggested-topics',
        kwargs={'job_id': research_job.id},
    )
    response = dmr_client.post(url, headers=auth_headers)
    assert response.status_code == HTTPStatus.OK
    titles = [
        idea['title'] for idea in response.json()['channel_spec']['seed_ideas']
    ]
    assert 'New Idea' in titles
