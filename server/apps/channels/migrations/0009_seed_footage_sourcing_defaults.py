"""Seed FootageSourcingConfig for channels missing a row; set provider default."""

from django.db import migrations, models
import django.contrib.***REMOVED***.fields


DEFAULT_ENABLED_PROVIDERS = [
    'pexels',
    'pixabay',
    'wikimedia',
    'openverse',
    'archive_org',
]


def _default_enabled_providers() -> list[str]:
    return list(DEFAULT_ENABLED_PROVIDERS)


def seed_missing_footage_sourcing(apps, schema_editor) -> None:
    Channel = apps.get_model('channels', 'Channel')
    FootageSourcingConfig = apps.get_model('channels', 'FootageSourcingConfig')
    existing = set(
        FootageSourcingConfig.objects.values_list('channel_id', flat=True),
    )
    to_create = [
        FootageSourcingConfig(
            channel_id=channel.id,
            enabled_providers=list(DEFAULT_ENABLED_PROVIDERS),
        )
        for channel in Channel.objects.all()
        if channel.id not in existing
    ]
    if to_create:
        FootageSourcingConfig.objects.bulk_create(to_create)


def unseed_footage_sourcing(apps, schema_editor) -> None:
    """No reverse — leave rows in place."""


class Migration(migrations.Migration):
    """Backfill footage sourcing and change the ArrayField default."""

    dependencies = [
        ('channels', '0008_footagesourcingconfig'),
    ]

    operations = [
        migrations.AlterField(
            model_name='footagesourcingconfig',
            name='enabled_providers',
            field=django.contrib.***REMOVED***.fields.ArrayField(
                base_field=models.CharField(max_length=32),
                blank=True,
                default=_default_enabled_providers,
                help_text='Ordered provider priority. Order is significant.',
                size=None,
            ),
        ),
        migrations.RunPython(
            seed_missing_footage_sourcing,
            unseed_footage_sourcing,
        ),
    ]
