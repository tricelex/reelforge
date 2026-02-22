from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchjob",
            name="trend_data_raw",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Raw data from Google Trends, YouTube search, etc.",
            ),
        ),
        migrations.AlterField(
            model_name="researchjob",
            name="competitor_data_raw",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Raw competitor channel analysis data",
            ),
        ),
        migrations.AlterField(
            model_name="researchjob",
            name="gap_analysis_raw",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Raw gap detection and opportunity scoring data",
            ),
        ),
    ]
