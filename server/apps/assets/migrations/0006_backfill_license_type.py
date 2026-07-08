"""Backfill license_type for LibraryAsset rows that predate license tracking.

Migration 0005 added `license_type` (default UNSPECIFIED) and the music_plan
stage now excludes UNSPECIFIED tracks from the selectable pool. Without this
backfill, every asset uploaded before license tracking existed would
silently disappear from the music/SFX pool on deploy.

Judgment call: rows that predate this feature are marked LICENSED (not
OWNED or ROYALTY_FREE_VERIFIED, which would overclaim) with a note flagging
them for manual review. This keeps the pipeline usable without asserting a
verified license status it can't actually confirm — operators should review
`license_note`-flagged rows and correct `license_type` where the real
licensing basis is known.
"""

from django.db import migrations

_BACKFILL_NOTE = (
    'Auto-backfilled on deploy of license tracking: this asset predates '
    'license_type and was marked LICENSED by default so it stays usable. '
    'Please verify and correct if the real licensing basis differs.'
)


def backfill_license_type(apps: object, schema_editor: object) -> None:
    """Mark every still-UNSPECIFIED row LICENSED with a review note."""
    library_asset_model = apps.get_model('assets', 'LibraryAsset')  # type: ignore[attr-defined]
    library_asset_model.objects.filter(license_type='UNSPECIFIED').update(
        license_type='LICENSED',
        license_note=_BACKFILL_NOTE,
    )


def unbackfill_license_type(apps: object, schema_editor: object) -> None:
    """Reverse: only rows still carrying our exact backfill note are reset."""
    library_asset_model = apps.get_model('assets', 'LibraryAsset')  # type: ignore[attr-defined]
    library_asset_model.objects.filter(license_note=_BACKFILL_NOTE).update(
        license_type='UNSPECIFIED',
        license_note='',
    )


class Migration(migrations.Migration):
    """Data migration: grandfather pre-existing LibraryAsset rows."""

    dependencies = [
        ('assets', '0005_libraryasset_license_note_libraryasset_license_type_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_license_type, unbackfill_license_type),
    ]
