# Generated manually — channel pipeline defaults and overrides

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('channels', '0002_character_source_run'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='config_overrides',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='channel',
            name='default_blueprint_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='channel',
            name='provider_daily_caps',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
