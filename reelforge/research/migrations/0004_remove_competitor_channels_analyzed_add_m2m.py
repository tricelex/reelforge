from __future__ import annotations

import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0003_revert_pydantic_field_to_json_field"),
        ("research", "0003_revert_pydantic_field_to_json_field"),
    ]

    operations = [
        # Add blank=True to search_keywords to prevent clean_fields() from rejecting empty list
        migrations.AlterField(
            model_name="researchjob",
            name="search_keywords",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=100),
                blank=True,
                default=list,
                help_text="Keywords used for this research run",
                size=None,
            ),
        ),
        # Remove the old competitor_channels_analyzed ArrayField
        migrations.RemoveField(
            model_name="researchjob",
            name="competitor_channels_analyzed",
        ),
        # Add M2M relationship to ChannelCompetitor
        migrations.AddField(
            model_name="researchjob",
            name="competitors_analyzed",
            field=models.ManyToManyField(
                blank=True,
                help_text="Competitor channels analyzed in this research run",
                related_name="research_jobs",
                to="channels.channelcompetitor",
            ),
        ),
    ]
