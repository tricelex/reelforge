"""Tests for the assets app's data migrations."""

from django_test_migrations.migrator import Migrator


def test_backfill_license_type_grandfathers_unspecified_rows(
    migrator: Migrator,
) -> None:
    """0006 marks pre-existing UNSPECIFIED rows LICENSED with a review note.

    The reverse migration resets only the rows it touched.
    """
    old_state = migrator.apply_initial_migration(
        (
            'assets',
            '0005_libraryasset_license_note_libraryasset_license_type_and_more',
        ),
    )
    library_asset_model = old_state.apps.get_model('assets', 'LibraryAsset')
    pre_existing = library_asset_model.objects.create(
        kind='MUSIC',
        name='Pre-existing track',
    )
    already_tagged = library_asset_model.objects.create(
        kind='MUSIC',
        name='Already tagged track',
        license_type='OWNED',
    )

    new_state = migrator.apply_tested_migration(
        ('assets', '0006_backfill_license_type'),
    )
    library_asset_model = new_state.apps.get_model('assets', 'LibraryAsset')
    backfilled = library_asset_model.objects.get(id=pre_existing.id)
    assert backfilled.license_type == 'LICENSED'
    assert 'Auto-backfilled' in backfilled.license_note

    untouched = library_asset_model.objects.get(id=already_tagged.id)
    assert untouched.license_type == 'OWNED'
    assert untouched.license_note == ''

    reverted_state = migrator.apply_tested_migration(
        (
            'assets',
            '0005_libraryasset_license_note_libraryasset_license_type_and_more',
        ),
    )
    library_asset_model = reverted_state.apps.get_model(
        'assets', 'LibraryAsset',
    )
    reverted = library_asset_model.objects.get(id=pre_existing.id)
    assert reverted.license_type == 'UNSPECIFIED'
    assert reverted.license_note == ''

    still_owned = library_asset_model.objects.get(id=already_tagged.id)
    assert still_owned.license_type == 'OWNED'
