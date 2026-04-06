from __future__ import annotations

from django.db import migrations


def create_default_template(apps: object, schema_editor: object) -> None:
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.get_or_create(
        is_default=True,
        defaults={
            "name": "Default Template",
            "caption_enabled": True,
            "caption_style": "CHUNKED",
            "caption_font": "Montserrat-Bold",
            "caption_size": 52,
            "caption_color": "#FFFFFF",
            "caption_stroke_color": "#000000",
            "caption_stroke_width": 3,
            "caption_bg_color": "",
            "caption_position": "BOTTOM",
            "caption_animation": "POP",
            "caption_language": "en",
            "caption_translate_to": "",
            "emoji_keyword_map": {},
            "hook_enabled": True,
            "hook_style": "OVERLAY_TOP",
            "hook_duration_sec": 2.5,
            "hook_font": "Montserrat-Bold",
            "hook_size": 60,
            "hook_color": "#FFFFFF",
            "hook_bg_color": "#CC000000",
            "hook_animation": "FADE",
            "intro_transition": "NONE",
            "outro_transition": "NONE",
            "transition_duration_sec": 0.5,
            "watermark_enabled": False,
            "watermark_type": "TEXT",
            "watermark_text": "",
            "watermark_position": "BOTTOM_RIGHT",
            "watermark_opacity": 0.6,
            "watermark_size": 32,
            "progress_bar_enabled": False,
            "progress_bar_position": "TOP",
            "progress_bar_color": "#FFFFFF",
            "progress_bar_height": 6,
            "music_enabled": False,
            "music_volume_db": -20.0,
            "music_fade_in_sec": 1.0,
            "music_fade_out_sec": 1.0,
        },
    )


def reverse_default_template(apps: object, schema_editor: object) -> None:
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.filter(name="Default Template", is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clipping", "0012_clippingjob_social_account_non_nullable"),
    ]

    operations = [
        migrations.RunPython(create_default_template, reverse_default_template),
    ]
