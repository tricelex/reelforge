"""Tests for clip source API."""

import uuid
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.channels.models import Channel, ChannelKind
from server.apps.clips.logic.constants import ClipSourceStatus, ClipSourceType
from server.apps.clips.models import ClipSource
from server.apps.clips.source_services import ClipSourceService


@pytest.fixture
def clipping_channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Clipping channel for source tests."""
    return Channel.objects.create(
        name='Clip Channel',
        kind=ChannelKind.CLIPPING,
    )


@pytest.mark.django_db
def test_upload_clip_source_create_and_list(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST upload source is READY immediately and appears in list."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Podcast Ep 1',
        file='library/ep1.mp4',
    )
    create_resp = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_type': ClipSourceType.UPLOAD,
            'library_asset_id': str(asset.id),
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED
    body = create_resp.json()
    assert body['channel_id'] == str(clipping_channel.id)
    assert body['status'] == ClipSourceStatus.READY
    assert body['title'] == 'Podcast Ep 1'
    assert body['run_id'] is None
    assert body['candidate_count'] == 0
    assert body['library_asset_id'] == str(asset.id)

    list_resp = dmr_client.get(
        reverse('api:clips:clip-source-collection'),
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert list_resp.json()['total'] == 1

    detail_resp = dmr_client.get(
        reverse(
            'api:clips:clip-source-detail',
            kwargs={'source_id': body['id']},
        ),
        headers=auth_headers,
    )
    assert detail_resp.status_code == HTTPStatus.OK
    detail = detail_resp.json()
    assert detail['id'] == body['id']
    assert detail['library_asset_id'] == str(asset.id)


@pytest.mark.django_db
def test_youtube_clip_source_probe(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """YouTube source probes metadata and becomes READY."""
    with patch(
        'server.apps.clips.source_services.kiq_task',
        new=lambda *_args, **_kwargs: None,
    ):
        create_resp = dmr_client.post(
            reverse('api:clips:clip-source-collection'),
            data={
                'channel_id': str(clipping_channel.id),
                'source_type': ClipSourceType.YOUTUBE,
                'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            },
            headers=auth_headers,
        )
    assert create_resp.status_code == HTTPStatus.CREATED
    source_id = create_resp.json()['id']
    assert create_resp.json()['status'] == ClipSourceStatus.INGESTING

    with patch(
        'server.apps.clips.tasks_api.probe_youtube_or_rss',
        return_value={'title': 'Test Video', 'duration_sec': 212.0},
    ):
        ClipSourceService().probe_now(source_id)

    detail = dmr_client.get(
        reverse(
            'api:clips:clip-source-detail',
            kwargs={'source_id': source_id},
        ),
        headers=auth_headers,
    )
    assert detail.status_code == HTTPStatus.OK
    body = detail.json()
    assert body['status'] == ClipSourceStatus.READY
    assert body['title'] == 'Test Video'
    assert body['duration_sec'] == 212.0


@pytest.mark.django_db
def test_clip_source_rejects_non_clipping_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST rejects sources on non-clipping channels."""
    channel = Channel.objects.create(
        name='Longform',
        kind=ChannelKind.LONGFORM,
    )
    response = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(channel.id),
            'source_type': ClipSourceType.YOUTUBE,
            'url': 'https://example.com/video',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ClipSource.objects.count() == 0


@pytest.mark.django_db
def test_clip_source_detail_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET missing clip source returns 404."""
    response = dmr_client.get(
        reverse(
            'api:clips:clip-source-detail',
            kwargs={'source_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_clip_source_list_invalid_limit(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET clip-sources tolerates invalid limit query param."""
    response = dmr_client.get(
        f"{reverse('api:clips:clip-source-collection')}?limit=abc",
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_create_run_from_clip_source(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST run with source_id links clip source and resolves topic."""
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1',
        defaults={
            'kind': PipelineKind.CLIPPING,
            'graph': {'stages': []},
            'is_active': True,
        },
    )
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Run Source',
        file='library/run-source.mp4',
    )
    create_resp = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_type': ClipSourceType.UPLOAD,
            'library_asset_id': str(asset.id),
        },
        headers=auth_headers,
    )
    source_id = create_resp.json()['id']

    with patch(
        'server.apps.pipelines.services.pipeline_run.kiq_advance_pipeline',
    ):
        run_resp = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={
                'channel_id': str(clipping_channel.id),
                'source_id': source_id,
            },
            headers=auth_headers,
        )
    assert run_resp.status_code == HTTPStatus.CREATED
    run_body = run_resp.json()
    linked = ClipSource.objects.get(id=source_id)
    assert linked.run_id is not None
    assert str(linked.run_id) == run_body['id']
    assert run_body['topic'] == 'Run Source'
    assert run_body['source_id'] == source_id

    detail_resp = dmr_client.get(
        reverse(
            'api:clips:clip-source-detail',
            kwargs={'source_id': source_id},
        ),
        headers=auth_headers,
    )
    assert detail_resp.json()['run_id'] == run_body['id']


@pytest.mark.django_db
def test_create_run_rejects_duplicate_source(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Second run start for the same source returns 409."""
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1',
        defaults={
            'kind': PipelineKind.CLIPPING,
            'graph': {'stages': []},
            'is_active': True,
        },
    )
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Duplicate Source',
        file='library/dup-source.mp4',
    )
    source_id = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_type': ClipSourceType.UPLOAD,
            'library_asset_id': str(asset.id),
        },
        headers=auth_headers,
    ).json()['id']

    with patch(
        'server.apps.pipelines.services.pipeline_run.kiq_advance_pipeline',
    ):
        first = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={
                'channel_id': str(clipping_channel.id),
                'source_id': source_id,
            },
            headers=auth_headers,
        )
        second = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={
                'channel_id': str(clipping_channel.id),
                'source_id': source_id,
            },
            headers=auth_headers,
        )
    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT


@pytest.mark.django_db
def test_create_run_rejects_mismatched_channel(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST run rejects source_id from a different channel."""
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    other_channel = Channel.objects.create(
        name='Other Clip Channel',
        kind=ChannelKind.CLIPPING,
    )
    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1',
        defaults={
            'kind': PipelineKind.CLIPPING,
            'graph': {'stages': []},
            'is_active': True,
        },
    )
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Mismatch Source',
        file='library/mismatch.mp4',
    )
    source_id = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_type': ClipSourceType.UPLOAD,
            'library_asset_id': str(asset.id),
        },
        headers=auth_headers,
    ).json()['id']

    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={
            'channel_id': str(other_channel.id),
            'source_id': source_id,
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_failed_clip_source_exposes_error_message(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """FAILED clip source returns error_message in API payload."""
    with patch(
        'server.apps.clips.source_services.kiq_task',
        new=lambda *_args, **_kwargs: None,
    ):
        source_id = dmr_client.post(
            reverse('api:clips:clip-source-collection'),
            data={
                'channel_id': str(clipping_channel.id),
                'source_type': ClipSourceType.YOUTUBE,
                'url': 'https://www.youtube.com/watch?v=fail',
            },
            headers=auth_headers,
        ).json()['id']

    with patch(
        'server.apps.clips.tasks_api.probe_youtube_or_rss',
        side_effect=RuntimeError('probe failed'),
    ):
        ClipSourceService().probe_now(source_id)

    detail = dmr_client.get(
        reverse(
            'api:clips:clip-source-detail',
            kwargs={'source_id': source_id},
        ),
        headers=auth_headers,
    )
    body = detail.json()
    assert body['status'] == ClipSourceStatus.FAILED
    assert body['error_message'] == 'probe failed'


@pytest.mark.django_db
def test_create_run_rejects_source_on_non_clipping_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST run with source_id rejects non-clipping channels."""
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    longform = Channel.objects.create(
        name='Longform Channel',
        kind=ChannelKind.LONGFORM,
    )
    clipping = Channel.objects.create(
        name='Clip Channel',
        kind=ChannelKind.CLIPPING,
    )
    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1',
        defaults={
            'kind': PipelineKind.CLIPPING,
            'graph': {'stages': []},
            'is_active': True,
        },
    )
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Wrong Channel Source',
        file='library/wrong-channel.mp4',
    )
    source_id = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(clipping.id),
            'source_type': ClipSourceType.UPLOAD,
            'library_asset_id': str(asset.id),
        },
        headers=auth_headers,
    ).json()['id']

    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={
            'channel_id': str(longform.id),
            'source_id': source_id,
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_create_run_rejects_missing_source(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST run with unknown source_id returns 400."""
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1',
        defaults={
            'kind': PipelineKind.CLIPPING,
            'graph': {'stages': []},
            'is_active': True,
        },
    )
    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_id': str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_create_run_rejects_topic_and_source_id(
    dmr_client: DMRClient,
    clipping_channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST run rejects providing both topic and source_id."""
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1',
        defaults={
            'kind': PipelineKind.CLIPPING,
            'graph': {'stages': []},
            'is_active': True,
        },
    )
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Conflict Source',
        file='library/conflict.mp4',
    )
    source_id = dmr_client.post(
        reverse('api:clips:clip-source-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_type': ClipSourceType.UPLOAD,
            'library_asset_id': str(asset.id),
        },
        headers=auth_headers,
    ).json()['id']

    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={
            'channel_id': str(clipping_channel.id),
            'source_id': source_id,
            'topic': 'also set',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
