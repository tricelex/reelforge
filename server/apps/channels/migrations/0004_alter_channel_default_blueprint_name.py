# Generated manually — use empty string instead of null for default_blueprint_name

from django.db import migrations, models


def _null_blueprints_to_empty(apps, schema_editor) -> None:
    channel = apps.get_model('channels', 'Channel')
    channel.objects.filter(default_blueprint_name__isnull=True).update(
        default_blueprint_name='',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('channels', '0003_channel_pipeline_config'),
    ]

    operations = [
        migrations.RunPython(
            _null_blueprints_to_empty,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='channel',
            name='default_blueprint_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
