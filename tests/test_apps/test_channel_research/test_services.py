"""Tests for ChannelResearchService."""

from unittest.mock import patch

import msgspec
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
)
from server.apps.channel_research.logic.schemas import (
    ChannelResearchAgentOutput,
)
from server.apps.channel_research.logic.value_objects import (
    ChannelResearchCreatePayload,
    ChannelResearchSpecPatchPayload,
    ChannelSpecPayload,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.services import ChannelResearchService
from server.common import container as container_module


@pytest.fixture
def service() -> ChannelResearchService:
    return container_module.container.resolve(ChannelResearchService)


@pytest.mark.django_db
def test_create_enqueues_and_sets_queued(
    service: ChannelResearchService,
    api_user: User,
) -> None:
    with patch(
        'server.apps.channel_research.services.kiq_task',
    ) as mock_kiq:
        payload = service.create(
            ChannelResearchCreatePayload(
                source_channel_url='https://www.youtube.com/@HistoryHub',
                working_name='Forge History',
            ),
            created_by_id=api_user.pk,
        )
    assert payload.status == ChannelResearchStatus.QUEUED
    assert payload.working_name == 'Forge History'
    assert payload.kind == ChannelResearchKind.LONGFORM
    mock_kiq.assert_called_once()
    job = ChannelResearchJob.objects.get(id=payload.id)
    assert job.created_by_id == api_user.pk


@pytest.mark.django_db
def test_create_rejects_non_youtube_url(
    service: ChannelResearchService,
) -> None:
    with pytest.raises(ValidationError, match='YouTube channel URL'):
        service.create(
            ChannelResearchCreatePayload(
                source_channel_url='https://vimeo.com/123',
            ),
            created_by_id=None,
        )


@pytest.mark.django_db
def test_create_rejects_blank_url(service: ChannelResearchService) -> None:
    with pytest.raises(ValidationError, match='required'):
        service.create(
            ChannelResearchCreatePayload(source_channel_url='   '),
            created_by_id=None,
        )


@pytest.mark.django_db
def test_create_rejects_invalid_kind(
    service: ChannelResearchService,
) -> None:
    with pytest.raises(ValidationError, match='Invalid kind'):
        service.create(
            ChannelResearchCreatePayload(
                source_channel_url='https://youtube.com/@x',
                kind='PODCAST',
            ),
            created_by_id=None,
        )


@pytest.mark.django_db
def test_patch_spec_only_when_succeeded(
    service: ChannelResearchService,
    research_job: ChannelResearchJob,
    agent_output: ChannelResearchAgentOutput,
) -> None:
    spec_payload = msgspec.convert(
        agent_output.channel_spec.model_dump(),
        type=ChannelSpecPayload,
    )
    with pytest.raises(ValidationError, match='SUCCEEDED'):
        service.patch_spec(
            str(research_job.id),
            ChannelResearchSpecPatchPayload(channel_spec=spec_payload),
        )
    research_job.status = ChannelResearchStatus.SUCCEEDED
    research_job.research_report = agent_output.research_report.model_dump()
    research_job.save(update_fields=['status', 'research_report'])
    edited = agent_output.channel_spec.model_dump()
    edited['channel']['name'] = 'edited'
    result = service.patch_spec(
        str(research_job.id),
        ChannelResearchSpecPatchPayload(
            channel_spec=msgspec.convert(edited, type=ChannelSpecPayload),
        ),
    )
    assert result.channel_spec is not None
    assert result.channel_spec.channel.name == 'edited'


@pytest.mark.django_db
def test_retry_failed_job(
    service: ChannelResearchService,
    research_job: ChannelResearchJob,
) -> None:
    research_job.status = ChannelResearchStatus.FAILED
    research_job.error_message = 'boom'
    research_job.channel_spec = {'stale': True}
    research_job.save()
    with patch('server.apps.channel_research.services.kiq_task'):
        result = service.retry(str(research_job.id))
    assert result.status == ChannelResearchStatus.QUEUED
    assert result.error_message == ''
    assert result.channel_spec is None


@pytest.mark.django_db
def test_retry_rejects_running_job(
    service: ChannelResearchService,
    research_job: ChannelResearchJob,
) -> None:
    research_job.status = ChannelResearchStatus.RUNNING
    research_job.save(update_fields=['status'])
    with pytest.raises(ValidationError, match='FAILED or SUCCEEDED'):
        service.retry(str(research_job.id))


@pytest.mark.django_db
def test_list_jobs_filters_status(
    service: ChannelResearchService,
    research_job: ChannelResearchJob,
) -> None:
    listed = service.list_jobs(
        status=ChannelResearchStatus.PENDING,
        cursor=None,
        limit=20,
    )
    assert listed.total == 1
    assert listed.items[0].id == str(research_job.id)
    empty = service.list_jobs(
        status=ChannelResearchStatus.SUCCEEDED,
        cursor=None,
        limit=20,
    )
    assert empty.total == 0


@pytest.mark.django_db
def test_validate_spec_returns_ok_and_errors(
    service: ChannelResearchService,
    agent_output: ChannelResearchAgentOutput,
) -> None:
    payload = msgspec.convert(
        agent_output.channel_spec.model_dump(),
        type=ChannelSpecPayload,
    )
    ok = service.validate_spec(payload)
    assert ok.ok is True
    assert ok.errors == []
    bad_dump = agent_output.channel_spec.model_dump()
    bad_dump['niche']['lore_document'] = 'Too short. We never do this.'
    bad = service.validate_spec(
        msgspec.convert(bad_dump, type=ChannelSpecPayload),
    )
    assert bad.ok is False
    assert bad.errors
