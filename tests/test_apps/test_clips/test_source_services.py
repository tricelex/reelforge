"""Unit tests for clip source service, probe, and selectors."""

import asyncio
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.channels.models import Channel, ChannelKind
from server.apps.clips.logic.constants import ClipSourceStatus, ClipSourceType
from server.apps.clips.logic.value_objects import ClipSourceCreatePayload
from server.apps.clips.models import ClipCampaign, ClipSource
from server.apps.clips.source_probe import probe_youtube_or_rss
from server.apps.clips.source_selectors import list_clip_sources
from server.apps.clips.source_services import ClipSourceService, _resolve_topic
from server.apps.clips.tasks import _probe_clip_source_sync


@pytest.fixture
def clipping_channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(name='Svc Channel', kind=ChannelKind.CLIPPING)


@pytest.mark.django_db
def test_list_clip_sources_empty_url(clipping_channel: Channel) -> None:
    """list_clip_sources returns empty url when source has no url or asset."""
    ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='',
        status=ClipSourceStatus.INGESTING,
    )
    result = list_clip_sources()
    assert result.items[0].url == ''


@pytest.mark.django_db
def test_probe_clip_source_task_delegates(
    clipping_channel: Channel,
) -> None:
    """probe_clip_source_task wraps the sync probe helper."""
    from server.apps.clips.tasks import probe_clip_source_task

    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='https://example.com/v',
        status=ClipSourceStatus.INGESTING,
    )
    with patch(
        'server.apps.clips.tasks._probe_clip_source_sync',
    ) as mock_probe:
        asyncio.run(probe_clip_source_task(str(source.id)))
    mock_probe.assert_called_once_with(str(source.id))


@pytest.mark.django_db
def test_list_clip_sources_filters(clipping_channel: Channel) -> None:
    """list_clip_sources supports channel and status filters."""
    ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='https://example.com/a',
        status=ClipSourceStatus.READY,
    )
    result = list_clip_sources(
        channel_id=str(clipping_channel.id),
        status=ClipSourceStatus.READY,
    )
    assert result.total == 1


@pytest.mark.django_db
def test_create_clip_source_with_campaign(clipping_channel: Channel) -> None:
    """create links optional campaign."""
    campaign = ClipCampaign.objects.create(
        channel=clipping_channel,
        name='Batch',
    )
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Asset',
        file='library/a.mp4',
    )
    service = ClipSourceService()
    with patch(
        'server.apps.clips.source_services.kiq_task',
        new=lambda *_a, **_k: None,
    ):
        payload = service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.YOUTUBE,
                url='https://example.com/v',
                campaign_id=str(campaign.id),
            ),
        )
    assert payload.campaign_id == str(campaign.id)


@pytest.mark.django_db
def test_create_clip_source_validation_errors(
    clipping_channel: Channel,
) -> None:
    """create raises ValidationError for invalid inputs."""
    service = ClipSourceService()
    with pytest.raises(ValidationError, match='Channel not found'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(uuid.uuid4()),
                source_type=ClipSourceType.UPLOAD,
                library_asset_id=str(uuid.uuid4()),
            ),
        )
    with pytest.raises(ValidationError, match='Campaign not found'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.UPLOAD,
                library_asset_id=str(uuid.uuid4()),
                campaign_id=str(uuid.uuid4()),
            ),
        )
    with pytest.raises(ValidationError, match='library_asset_id is required'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.UPLOAD,
            ),
        )
    with pytest.raises(ValidationError, match='Library asset not found'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.UPLOAD,
                library_asset_id=str(uuid.uuid4()),
            ),
        )
    with pytest.raises(ValidationError, match='url is required'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.YOUTUBE,
                url='',
            ),
        )
    with pytest.raises(ValidationError, match='url is required'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.RSS,
                url='',
            ),
        )
    with patch(
        'server.apps.clips.source_services.kiq_task',
        new=lambda *_a, **_k: None,
    ):
        youtube_payload = service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.YOUTUBE,
                url='https://example.com/watch?v=abc',
            ),
        )
    assert youtube_payload.url == 'https://example.com/watch?v=abc'
    with patch(
        'server.apps.clips.source_services.kiq_task',
        new=lambda *_a, **_k: None,
    ):
        rss_payload = service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type=ClipSourceType.RSS,
                url='https://example.com/feed.xml',
            ),
        )
    assert rss_payload.url == 'https://example.com/feed.xml'
    with pytest.raises(ValidationError, match='Invalid source_type'):
        service.create(
            ClipSourceCreatePayload(
                channel_id=str(clipping_channel.id),
                source_type='invalid',
            ),
        )


@pytest.mark.django_db
def test_resolve_topic_and_run_helpers(clipping_channel: Channel) -> None:
    """resolve_topic_for_run and link_run enforce readiness."""
    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='https://example.com/v',
        status=ClipSourceStatus.INGESTING,
    )
    service = ClipSourceService()
    with pytest.raises(ValidationError, match='not ready'):
        service.resolve_topic_for_run(str(source.id))

    source.status = ClipSourceStatus.READY
    source.save(update_fields=['status'])
    assert service.resolve_topic_for_run(str(source.id)) == source.url
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind, PipelineRun

    blueprint = PipelineBlueprint.objects.create(
        name='clip_link_test',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=clipping_channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic=source.url,
    )
    service.link_run(str(source.id), str(run.id))


@pytest.mark.django_db
def test_resolve_topic_upload_missing_asset(clipping_channel: Channel) -> None:
    """_resolve_topic validates upload sources."""
    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.UPLOAD,
        status=ClipSourceStatus.READY,
    )
    with pytest.raises(ValidationError, match='library_asset_id'):
        _resolve_topic(source)


def test_probe_youtube_or_rss() -> None:
    """probe_youtube_or_rss delegates to yt-dlp."""
    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = {
        'title': 'Probe Title',
        'duration': 90,
    }
    with patch.dict(sys.modules, {'yt_dlp': mock_ytdlp}):
        info = probe_youtube_or_rss('https://example.com/v')
    assert info['title'] == 'Probe Title'
    assert info['duration_sec'] == 90.0


@pytest.mark.django_db
def test_resolve_topic_missing_url(clipping_channel: Channel) -> None:
    """_resolve_topic requires URL for remote sources."""
    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='',
        status=ClipSourceStatus.READY,
    )
    with pytest.raises(ValidationError, match='Source URL is required'):
        _resolve_topic(source)


@pytest.mark.django_db
def test_probe_clip_source_sync_success(clipping_channel: Channel) -> None:
    """Successful probe marks source READY."""
    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='https://example.com/v',
        status=ClipSourceStatus.INGESTING,
    )
    with patch(
        'server.apps.clips.tasks.probe_youtube_or_rss',
        return_value={'title': 'Done', 'duration_sec': 10.0},
    ):
        _probe_clip_source_sync(str(source.id))
    source.refresh_from_db()
    assert source.status == ClipSourceStatus.READY


@pytest.mark.django_db
def test_probe_clip_source_sync_failure(clipping_channel: Channel) -> None:
    """Failed probe marks source FAILED."""
    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.YOUTUBE,
        url='https://example.com/v',
        status=ClipSourceStatus.INGESTING,
    )
    with patch(
        'server.apps.clips.tasks.probe_youtube_or_rss',
        side_effect=RuntimeError('probe failed'),
    ):
        _probe_clip_source_sync(str(source.id))
    source.refresh_from_db()
    assert source.status == ClipSourceStatus.FAILED
    assert 'probe failed' in source.error_message


@pytest.mark.django_db
def test_probe_clip_source_sync_skips_upload(clipping_channel: Channel) -> None:
    """Upload sources are not probed asynchronously."""
    source = ClipSource.objects.create(
        channel=clipping_channel,
        source_type=ClipSourceType.UPLOAD,
        library_asset_id=uuid.uuid4(),
        status=ClipSourceStatus.READY,
    )
    _probe_clip_source_sync(str(source.id))
    source.refresh_from_db()
    assert source.status == ClipSourceStatus.READY
