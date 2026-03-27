from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django_fsm.signals import post_transition

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClippingJob

logger = logging.getLogger("***REMOVED***.clipping")


def on_clipping_job_transition(sender, instance, name, source, target, **kwargs):
    """Log ClippingJob FSM failures."""
    if target == ClippingJob.Status.FAILED:
        logger.error(
            "ClippingJob failed",
            extra={"clipping_job_id": str(instance.id), "last_error": instance.last_error},
        )


post_transition.connect(on_clipping_job_transition, sender=ClippingJob)


@receiver(post_save, sender=ClipCandidate)
def create_layout_config_for_candidate(
    sender,
    instance: ClipCandidate,
    created: bool,
    **kwargs,
) -> None:
    """Auto-create a ClipLayoutConfig when a ClipCandidate is first saved.

    Pre-populates from channel.default_render_mode and channel.default_layout_config
    so new candidates inherit the channel's preferred layout without manual setup.
    """
    if not created:
        return
    channel = instance.clipping_job.channel
    channel_defaults: dict = channel.default_layout_config or {}
    ClipLayoutConfig.objects.get_or_create(
        candidate=instance,
        defaults={
            "render_mode": channel.default_render_mode,
            **channel_defaults,
        },
    )
