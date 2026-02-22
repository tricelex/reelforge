from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assetjob",
            name="visual_timeline",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Composited timeline driving VideoRenderer — maps time windows to images.",
                verbose_name="Visual Timeline",
            ),
        ),
    ]
