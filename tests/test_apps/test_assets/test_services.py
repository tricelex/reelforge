from unittest.mock import MagicMock

import pytest

from server.apps.assets.logic.events import LibraryAssetIngested
from server.apps.assets.logic.value_objects import (
    LibraryAssetCreatePayload,
    LibraryAssetPayload,
)
from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.assets.services import LibraryAssetService
from server.common.events import InProcessEventBus
from server.common.storage import PresignUrlHelper


def _make_presign() -> MagicMock:
    presign = MagicMock(spec=PresignUrlHelper)
    presign.presign_get.return_value = 'https://storage.example/file'
    return presign


def _make_service() -> LibraryAssetService:
    return LibraryAssetService(
        events=InProcessEventBus(),
        presign=_make_presign(),
    )


@pytest.mark.django_db
def test_register_from_key_creates_library_asset() -> None:
    service = _make_service()
    payload = LibraryAssetCreatePayload(
        kind=LibraryAssetKind.MUSIC,
        name='Epic Strings',
        storage_key='uploads/test/epic.mp3',
        tags=['tense'],
    )

    result = service.register_from_key(payload)

    assert isinstance(result, LibraryAssetPayload)
    assert result.name == 'Epic Strings'
    assert result.tags == ['tense']
    assert result.url == 'https://storage.example/file'
    assert result.mime == 'audio/mpeg'
    assert LibraryAsset.objects.filter(id=result.id).exists()


@pytest.mark.django_db
def test_register_from_key_uses_explicit_mime() -> None:
    service = _make_service()
    payload = LibraryAssetCreatePayload(
        kind=LibraryAssetKind.MUSIC,
        name='Custom MIME',
        storage_key='uploads/test/track.bin',
        mime='audio/mp4',
    )

    result = service.register_from_key(payload)

    assert result.mime == 'audio/mp4'
    assert LibraryAsset.objects.get(id=result.id).mime == 'audio/mp4'


@pytest.mark.django_db
def test_register_from_key_emits_library_asset_ingested() -> None:
    events: list[LibraryAssetIngested] = []
    bus = InProcessEventBus()
    bus.subscribe(LibraryAssetIngested, events.append)

    service = LibraryAssetService(
        events=bus,
        presign=_make_presign(),
    )
    payload = LibraryAssetCreatePayload(
        kind=LibraryAssetKind.WATERMARK,
        name='Logo',
        storage_key='uploads/test/logo.png',
    )

    result = service.register_from_key(payload)

    assert len(events) == 1
    assert events[0].asset_id == str(result.id)


@pytest.mark.django_db
def test_register_from_key_with_channel(channel) -> None:
    service = _make_service()
    payload = LibraryAssetCreatePayload(
        kind=LibraryAssetKind.MUSIC,
        name='Channel Track',
        storage_key='uploads/test/track.mp3',
        channel_id=str(channel.id),
    )

    result = service.register_from_key(payload)

    asset = LibraryAsset.objects.get(id=result.id)
    assert asset.channel_id == channel.id


@pytest.mark.django_db
def test_list_assets_filters_by_kind(channel) -> None:
    service = _make_service()
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.MUSIC,
            name='Music A',
            storage_key='uploads/a.mp3',
        ),
    )
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.WATERMARK,
            name='Logo',
            storage_key='uploads/logo.png',
        ),
    )

    result = service.list_assets(kind=LibraryAssetKind.MUSIC)

    assert result.total == 1
    assert result.items[0].name == 'Music A'


@pytest.mark.django_db
def test_list_assets_filters_by_channel_id(channel) -> None:
    service = _make_service()
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.MUSIC,
            name='Channel Track',
            storage_key='uploads/channel.mp3',
            channel_id=str(channel.id),
        ),
    )
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.MUSIC,
            name='Global Track',
            storage_key='uploads/global.mp3',
        ),
    )

    result = service.list_assets(channel_id=str(channel.id))

    assert result.total == 1
    assert result.items[0].name == 'Channel Track'


@pytest.mark.django_db
def test_list_assets_filters_by_tag() -> None:
    service = _make_service()
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.MUSIC,
            name='Tagged',
            storage_key='uploads/tagged.mp3',
            tags=['ambient'],
        ),
    )
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.MUSIC,
            name='Untagged',
            storage_key='uploads/plain.mp3',
        ),
    )

    result = service.list_assets(tag='ambient')

    assert result.total == 1
    assert result.items[0].name == 'Tagged'
