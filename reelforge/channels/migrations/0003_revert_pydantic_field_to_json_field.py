from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="channel",
            name="oauth_credentials",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="channel",
            name="upload_schedule",
            field=models.JSONField(
                default=list,
                help_text="Ordered list of weekly upload time slots.",
            ),
        ),
    ]
