"""Tests for NexLev persistent record models."""

import pytest

from server.apps.nexlev.models import (
    NexLevChannelRecord,
    NexLevSearchCacheEntry,
    NexLevVideoRecord,
)


@pytest.mark.django_db
def test_channel_record_defaults() -> None:
    record = NexLevChannelRecord.objects.create(channel_id='UC123')
    assert record.about is None
    assert record.about_fetched_at is None
    assert record.quota_spent == 0
    assert str(record) == 'UC123'


@pytest.mark.django_db
def test_channel_record_channel_id_is_unique() -> None:
    NexLevChannelRecord.objects.create(channel_id='UC123')
    with pytest.raises(Exception, match='unique'):
        NexLevChannelRecord.objects.create(channel_id='UC123')


@pytest.mark.django_db
def test_video_record_defaults() -> None:
    record = NexLevVideoRecord.objects.create(video_id='v1')
    assert record.details is None
    assert record.quota_spent == 0
    assert str(record) == 'v1'


@pytest.mark.django_db
def test_search_cache_entry_stores_payload() -> None:
    entry = NexLevSearchCacheEntry.objects.create(
        cache_key='abc123',
        payload={'results': []},
    )
    assert entry.payload == {'results': []}
    assert str(entry) == 'abc123'
