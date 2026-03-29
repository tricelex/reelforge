from __future__ import annotations

from django.db import migrations


def populate_clip_style_configs(apps, schema_editor):
    """Create a ClipStyleConfig for every existing ClipCandidate."""
    ClipCandidate = apps.get_model("clipping", "ClipCandidate")
    ClipStyleConfig = apps.get_model("clipping", "ClipStyleConfig")
    for candidate in ClipCandidate.objects.select_related("clipping_job__channel").all():
        ClipStyleConfig.objects.get_or_create(candidate=candidate)


def reverse_populate_clip_style_configs(apps, schema_editor):
    ClipStyleConfig = apps.get_model("clipping", "ClipStyleConfig")
    ClipStyleConfig.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clipping", "0007_populate_clip_render_templates"),
    ]

    operations = [
        migrations.RunPython(
            populate_clip_style_configs,
            reverse_code=reverse_populate_clip_style_configs,
        ),
    ]
