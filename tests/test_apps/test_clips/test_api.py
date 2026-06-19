"""Tests for the clips API controllers."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import msgspec
import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.clips.logic.constants import CandidateStatus
from server.apps.clips.logic.value_objects import ClipCandidatePayload


@pytest.fixture()
def channel(db):  # type: ignore[no-untyped-def]
    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
        PublishMode,
    )

    return Channel.objects.create(
        name='Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture()
def blueprint(db):  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineKind,
    )

    return PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )


@pytest.fixture()
def run(channel, blueprint):  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=test',
    )


@pytest.fixture()
def candidate(run):  # type: ignore[no-untyped-def]
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    return ClipCandidate.objects.create(
        run=run,
        start_sec=10.0,
        end_sec=70.0,
        title='Test Clip',
    )


@pytest.mark.django_db
def test_list_candidates(
    dmr_client: DMRClient,
    candidate: object,
    run: object,
    auth_headers: dict[str, str],
) -> None:
    """Candidates for a run are returned as a list."""
    response = dmr_client.get(
        reverse('clips:candidate_list', kwargs={'run_id': run.id}),  # type: ignore[attr-defined]
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data) == 1
    parsed = msgspec.convert(data[0], type=ClipCandidatePayload)
    assert parsed.title == 'Test Clip'


@pytest.mark.django_db
def test_get_candidate(
    dmr_client: DMRClient,
    candidate: object,
    auth_headers: dict[str, str],
) -> None:
    """A single candidate is returned by ID."""
    response = dmr_client.get(
        reverse(
            'clips:candidate_detail',
            kwargs={'candidate_id': candidate.id},  # type: ignore[attr-defined]
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=ClipCandidatePayload)
    assert parsed.title == 'Test Clip'


@pytest.mark.django_db
def test_get_candidate_missing(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """404 is returned when candidate does not exist."""
    import uuid  # noqa: PLC0415

    response = dmr_client.get(
        reverse(
            'clips:candidate_detail',
            kwargs={'candidate_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {
        'detail': [{'msg': 'Candidate not found', 'type': 'not_found'}],
    }


@pytest.mark.django_db
def test_approve_candidate(
    dmr_client: DMRClient,
    candidate: object,
    auth_headers: dict[str, str],
) -> None:
    """Approving a candidate sets its status to APPROVED."""
    response = dmr_client.post(
        reverse(
            'clips:candidate_approve',
            kwargs={'candidate_id': candidate.id},  # type: ignore[attr-defined]
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=ClipCandidatePayload)
    assert parsed.status == CandidateStatus.APPROVED
    candidate.refresh_from_db()  # type: ignore[attr-defined]
    assert candidate.status == CandidateStatus.APPROVED  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_reject_candidate(
    dmr_client: DMRClient,
    candidate: object,
    auth_headers: dict[str, str],
) -> None:
    """Rejecting a candidate sets its status and records the reason."""
    response = dmr_client.post(
        reverse(
            'clips:candidate_reject',
            kwargs={'candidate_id': candidate.id},  # type: ignore[attr-defined]
        ),
        data={'reason': 'Not relevant'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=ClipCandidatePayload)
    assert parsed.status == CandidateStatus.REJECTED
    assert parsed.rejection_reason == 'Not relevant'
    candidate.refresh_from_db()  # type: ignore[attr-defined]
    assert candidate.status == CandidateStatus.REJECTED  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_reject_candidate_default_reason(
    dmr_client: DMRClient,
    candidate: object,
    auth_headers: dict[str, str],
) -> None:
    """Rejecting without a reason leaves rejection_reason blank."""
    response = dmr_client.post(
        reverse(
            'clips:candidate_reject',
            kwargs={'candidate_id': candidate.id},  # type: ignore[attr-defined]
        ),
        data={},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=ClipCandidatePayload)
    assert parsed.status == CandidateStatus.REJECTED
    assert parsed.rejection_reason == ''


@pytest.mark.django_db
def test_approve_gate(
    dmr_client: DMRClient,
    candidate: object,
    run: object,
    auth_headers: dict[str, str],
) -> None:
    """Gate approval endpoint calls approve_gate_impl and returns approved count."""
    approved_ids = [str(candidate.id)]  # type: ignore[attr-defined]

    with patch(
        'server.apps.pipelines.services.orchestrator.approve_gate_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse('clips:approve_gate', kwargs={'run_id': run.id}),  # type: ignore[attr-defined]
            data={'approved_candidate_ids': approved_ids},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['status'] == 'approved'
    assert data['approved_count'] == 1
