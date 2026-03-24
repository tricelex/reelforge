from __future__ import annotations

import logging

from django_fsm.signals import post_transition

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
