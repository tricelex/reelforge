# Generated manually for ClipCandidate.preview_asset_id

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('clips', '0004_clipsource'),
    ]

    operations = [
        migrations.AddField(
            model_name='clipcandidate',
            name='preview_asset_id',
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
