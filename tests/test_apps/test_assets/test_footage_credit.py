"""Tests for FOOTAGE asset kind and the FootageCredit provenance row."""

import pytest
from django.core.files.base import ContentFile

from server.apps.assets.models import Asset, AssetKind, FootageCredit


@pytest.mark.django_db
def test_footage_is_a_valid_asset_kind() -> None:
    """A FOOTAGE asset saves without violating the kind check constraint."""
    asset = Asset(kind=AssetKind.FOOTAGE, mime='video/mp4', checksum='abc')
    asset.file.save('clip.mp4', ContentFile(b'x'), save=False)
    asset.save()
    assert Asset.objects.filter(kind=AssetKind.FOOTAGE).count() == 1


@pytest.mark.django_db
def test_footage_credit_records_provenance() -> None:
    """A credit row links an asset to its provider licence terms."""
    asset = Asset(kind=AssetKind.FOOTAGE, mime='image/jpeg', checksum='def')
    asset.file.save('still.jpg', ContentFile(b'x'), save=False)
    asset.save()

    credit = FootageCredit.objects.create(
        asset=asset,
        scene_idx=4,
        provider='wikimedia',
        license='CC-BY-4.0',
        license_url='https://creativecommons.org/licenses/by/4.0/',
        author='A Photographer',
        source_url='https://commons.wikimedia.org/wiki/File:X.jpg',
        title='A Photograph',
        attribution_required=True,
    )
    assert credit.attribution_required is True
    assert asset.credits.count() == 1
    assert str(credit) == 'wikimedia CC-BY-4.0 (scene 4)'


@pytest.mark.django_db
def test_footage_credit_defaults_to_no_attribution() -> None:
    """Providers like Pexels do not require attribution by default."""
    asset = Asset(kind=AssetKind.FOOTAGE, mime='video/mp4', checksum='ghi')
    asset.file.save('clip.mp4', ContentFile(b'x'), save=False)
    asset.save()
    credit = FootageCredit.objects.create(
        asset=asset,
        scene_idx=0,
        provider='pexels',
        license='pexels',
        source_url='https://www.pexels.com/video/1/',
    )
    assert credit.attribution_required is False
    assert credit.author == ''
