import pytest

from server.apps.assets.models import (
    Asset,
    AssetKind,
    AssetRendition,
    LibraryAsset,
    LibraryAssetKind,
)
from server.common.s3 import AssetStorage


def test_asset_kind_values() -> None:
    assert set(AssetKind.values) == {
        'IMAGE',
        'VIDEO_SEGMENT',
        'AUDIO_VO',
        'SUBTITLE',
        'FINAL_VIDEO',
        'THUMBNAIL',
        'TRANSCRIPT',
        'DOC',
        'FOOTAGE',
    }


def test_library_asset_kind_values() -> None:
    assert set(LibraryAssetKind.values) == {
        'WATERMARK',
        'INTRO',
        'OUTRO',
        'OVERLAY',
        'TRANSITION',
        'MUSIC',
        'SFX',
        'FONT',
        'BACKGROUND',
        'CHARACTER_REF',
        'CAPTION_STYLE',
        'LUT',
    }


def test_asset_storage_class_is_importable() -> None:
    assert AssetStorage is not None


def test_library_asset_defaults() -> None:
    la = LibraryAsset(kind=LibraryAssetKind.MUSIC, name='Epic Strings')
    assert la.is_active is True
    assert la.version == 1
    assert la.tags == []
    assert la.meta == {}
    assert la.mime == ''


def test_library_asset_str() -> None:
    la = LibraryAsset(kind=LibraryAssetKind.WATERMARK, name='Logo 2025')
    assert str(la) == 'Logo 2025'


def test_asset_meta_default() -> None:
    a = Asset(kind=AssetKind.IMAGE, mime='image/png', checksum='abc123')
    assert a.meta == {}


def test_asset_str() -> None:
    a = Asset(kind=AssetKind.IMAGE, mime='image/png', checksum='x')
    assert 'IMAGE' in str(a)


# DB tests — activated once migrations are applied
@pytest.mark.django_db
def test_library_asset_creation() -> None:
    la = LibraryAsset.objects.create(
        kind=LibraryAssetKind.MUSIC,
        name='Epic Strings',
        tags=['tense', 'orchestral'],
    )
    assert la.id is not None
    assert la.tags == ['tense', 'orchestral']
    assert la.is_active is True
    assert la.version == 1


@pytest.mark.django_db
def test_asset_rendition_links_to_library_asset() -> None:
    la = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Intro Clip',
    )
    rendition = AssetRendition.objects.create(
        source=la,
        profile='1080p30_h264',
    )
    assert rendition.source_id == la.id
    assert '1080p30_h264' in str(rendition)


@pytest.mark.django_db
def test_asset_creation() -> None:
    a = Asset.objects.create(
        kind=AssetKind.THUMBNAIL,
        mime='image/jpeg',
        checksum='deadbeef' * 8,
    )
    assert a.id is not None
    assert a.meta == {}


def test_asset_upload_path_contains_kind_and_filename() -> None:
    from server.apps.assets.models import asset_upload_path

    asset = Asset(kind=AssetKind.IMAGE)
    path = asset_upload_path(asset, 'photo.jpg')
    assert path.startswith('generated/IMAGE/')
    assert path.endswith('/photo.jpg')
