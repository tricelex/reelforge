
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from server.apps.assets.logic.events import LibraryAssetIngested
from server.apps.assets.logic.value_objects import (
    LibraryAssetPayload,
    LibraryAssetRegisterPayload,
)
from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.assets.services import LibraryAssetService
from server.common.events import InProcessEventBus


def _make_service() -> LibraryAssetService:
    return LibraryAssetService(events=InProcessEventBus())


@pytest.mark.django_db
def test_register_creates_library_asset() -> None:
    service = _make_service()
    file = SimpleUploadedFile('epic.mp3', b'audio data', content_type='audio/mpeg')
    payload = LibraryAssetRegisterPayload(
        kind=LibraryAssetKind.MUSIC, name='Epic Strings', tags=['tense'],
    )

    result = service.register(payload, file)

    assert isinstance(result, LibraryAssetPayload)
    assert result.name == 'Epic Strings'
    assert result.tags == ['tense']
    assert LibraryAsset.objects.filter(id=result.id).exists()


@pytest.mark.django_db
def test_register_emits_library_asset_ingested() -> None:
    events: list[LibraryAssetIngested] = []
    bus = InProcessEventBus()
    bus.subscribe(LibraryAssetIngested, events.append)

    service = LibraryAssetService(events=bus)
    file = SimpleUploadedFile('logo.png', b'\x89PNG', content_type='image/png')
    payload = LibraryAssetRegisterPayload(
        kind=LibraryAssetKind.WATERMARK, name='Logo',
    )

    result = service.register(payload, file)

    assert len(events) == 1
    assert events[0].asset_id == str(result.id)


@pytest.mark.django_db
def test_register_with_channel(channel) -> None:
    service = _make_service()
    file = SimpleUploadedFile('track.mp3', b'data', content_type='audio/mpeg')
    payload = LibraryAssetRegisterPayload(
        kind=LibraryAssetKind.MUSIC,
        name='Channel Track',
        channel_id=channel.id,
    )

    result = service.register(payload, file)

    asset = LibraryAsset.objects.get(id=result.id)
    assert asset.channel_id == channel.id
