from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scriptjob",
            name="research_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Facts, stats, sources gathered during script research",
            ),
        ),
        migrations.AlterField(
            model_name="scriptjob",
            name="generated_hooks",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Agent-generated hook variations for the video opening.",
            ),
        ),
        migrations.AlterField(
            model_name="scriptjob",
            name="qa_issues_found",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="QA issues found in the script.",
            ),
        ),
        migrations.AlterField(
            model_name="scriptjob",
            name="qa_issues_fixed",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="QA issues that have been resolved.",
            ),
        ),
        migrations.AlterField(
            model_name="scriptjob",
            name="chapters",
            field=models.JSONField(
                default=list,
                help_text="YouTube chapter markers for the video.",
            ),
        ),
        migrations.AlterField(
            model_name="scriptjob",
            name="broll_suggestions",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="B-roll cues consumed by AssetJob for image generation.",
            ),
        ),
        migrations.AlterField(
            model_name="scriptjob",
            name="segments",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Pre-chunked TTS segments driving VoiceoverSegment creation.",
            ),
        ),
    ]
