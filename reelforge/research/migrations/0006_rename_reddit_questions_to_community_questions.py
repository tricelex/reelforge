from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0005_alter_researchjob_competitor_data_raw_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="topicidea",
            old_name="reddit_questions",
            new_name="community_questions",
        ),
    ]
