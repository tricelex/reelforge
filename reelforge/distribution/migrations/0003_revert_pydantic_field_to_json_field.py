from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("distribution", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analyticssnapshot",
            name="traffic_source_data",
            field=models.JSONField(
                default=dict,
                help_text="YouTube Analytics traffic source breakdown: source_name → percentage.",
            ),
        ),
        migrations.AlterField(
            model_name="analyticssnapshot",
            name="ai_insights",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="AI-generated performance analysis for the research feedback loop.",
            ),
        ),
    ]
