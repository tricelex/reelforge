from __future__ import annotations

from django.db import migrations


def populate_clip_render_templates(apps, schema_editor):
    """Create a ClipRenderTemplate for every existing Channel."""
    Channel = apps.get_model("channels", "Channel")
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    for channel in Channel.objects.all():
        ClipRenderTemplate.objects.get_or_create(channel=channel)


def reverse_populate_clip_render_templates(apps, schema_editor):
    """Remove all ClipRenderTemplate records (migration reversal only)."""
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clipping", "0006_add_style_config_timed_overlay_stage_result"),
        ("channels", "0011_channel_default_render_mode"),
    ]

    operations = [
        migrations.RunPython(
            populate_clip_render_templates,
            reverse_code=reverse_populate_clip_render_templates,
        ),
    ]
