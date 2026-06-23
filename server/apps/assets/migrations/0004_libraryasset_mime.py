"""Add mime field to LibraryAsset."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add optional MIME type to library assets."""

    dependencies = [
        ('assets', '0003_asset_pipeline_fks'),
    ]

    operations = [
        migrations.AddField(
            model_name='libraryasset',
            name='mime',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
