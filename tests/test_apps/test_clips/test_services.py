"""Tests for ClipCandidateService."""

import pytest

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.clips.logic.constants import CandidateStatus
from server.apps.clips.logic.value_objects import ClipCandidatePayload
from server.apps.clips.models import ClipCandidate
from server.apps.clips.services import ClipCandidateService
from server.apps.pipelines.models import PipelineBlueprint, PipelineKind, PipelineRun


@pytest.fixture()
def candidate(db: None) -> ClipCandidate:
    channel = Channel.objects.create(
        name='Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    bp = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=test',
    )
    return ClipCandidate.objects.create(
        run=run, start_sec=10.0, end_sec=70.0, title='Test Clip',
    )


@pytest.mark.django_db
def test_list_for_run(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    results = svc.list_for_run(str(candidate.run_id))
    assert len(results) == 1
    assert results[0].title == 'Test Clip'
    assert results[0].status == CandidateStatus.PROPOSED


@pytest.mark.django_db
def test_list_for_run_empty(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    results = svc.list_for_run('00000000-0000-0000-0000-000000000000')
    assert results == []


@pytest.mark.django_db
def test_approve(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    result = svc.approve(str(candidate.id))
    assert result.status == CandidateStatus.APPROVED
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_reject(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    result = svc.reject(str(candidate.id), reason='Not relevant')
    assert result.status == CandidateStatus.REJECTED
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.rejection_reason == 'Not relevant'


@pytest.mark.django_db
def test_reject_default_reason(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    result = svc.reject(str(candidate.id))
    assert result.rejection_reason == ''


@pytest.mark.django_db
def test_get_by_id(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    result = svc.get_by_id(str(candidate.id))
    assert result.id == str(candidate.id)
    assert isinstance(result, ClipCandidatePayload)


@pytest.mark.django_db
def test_approved_for_run(candidate: ClipCandidate) -> None:
    candidate.status = CandidateStatus.APPROVED
    candidate.save(update_fields=['status'])
    svc = ClipCandidateService()
    approved = svc.approved_for_run(str(candidate.run_id))
    assert len(approved) == 1
    assert approved[0].status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_approved_for_run_empty_when_proposed(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    approved = svc.approved_for_run(str(candidate.run_id))
    assert approved == []


@pytest.mark.django_db
def test_payload_duration_sec(candidate: ClipCandidate) -> None:
    svc = ClipCandidateService()
    result = svc.get_by_id(str(candidate.id))
    assert result.duration_sec == 60.0
