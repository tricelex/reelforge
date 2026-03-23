from __future__ import annotations

import logging

from django_fsm.signals import post_transition

from reelforge.clipping.models import ClippingJob

logger = logging.getLogger("reelforge.clipping")


def on_clipping_job_transition(sender, instance, name, source, target, **kwargs):
    """Dispatch Celery tasks based on ClippingJob FSM transitions."""
    from reelforge.clipping.tasks import analyze_clips
    from reelforge.clipping.tasks import download_source_video
    from reelforge.clipping.tasks import transcribe_video

    job_id = str(instance.id)

    if target == ClippingJob.Status.DOWNLOADING:
        download_source_video.delay(job_id)

    elif target == ClippingJob.Status.TRANSCRIBING:
        # Triggered directly in download_source_video task
        pass

    elif target == ClippingJob.Status.ANALYZING:
        # Triggered directly in transcribe_video task
        pass

    elif target == ClippingJob.Status.FAILED:
        logger.error(
            "ClippingJob failed",
            extra={"clipping_job_id": job_id, "last_error": instance.last_error},
        )


post_transition.connect(on_clipping_job_transition, sender=ClippingJob)
