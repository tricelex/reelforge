from __future__ import annotations

from django.apps import AppConfig


class ClippingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reelforge.clipping"
    verbose_name = "Clipping"

    def ready(self) -> None:
        import reelforge.clipping.signals  # noqa: F401

        # Connect Channel post_save here (not in signals.py) to avoid circular
        # imports: clipping.models imports channels.models, so importing
        # channels.models again in signals.py at module level would be circular.
        from django.db.models.signals import post_save

        from reelforge.channels.models import Channel
        from reelforge.clipping.signals import create_clip_render_template_for_channel

        post_save.connect(create_clip_render_template_for_channel, sender=Channel)
