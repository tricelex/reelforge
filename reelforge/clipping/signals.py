from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django_fsm.signals import post_transition

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClipMediaAsset
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipMusicAsset
from reelforge.clipping.models import ClipRenderTemplate
from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.clipping")


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


@receiver(post_save, sender=ClipCandidate)
def create_style_config_for_candidate(
    sender,
    instance: ClipCandidate,
    created: bool,
    **kwargs,
) -> None:
    """Auto-create a ClipStyleConfig when a ClipCandidate is first saved.

    Pre-populates all style fields from the channel's ClipRenderTemplate.
    """
    if not created:
        return
    channel = instance.clipping_job.channel
    template = ClipRenderTemplate.objects.filter(channel=channel).first()
    style_defaults = template.to_style_defaults() if template is not None else {}

    ClipStyleConfig.objects.get_or_create(
        candidate=instance,
        defaults=style_defaults,
    )


@receiver(post_save, sender=ClipMediaAsset)
def detect_media_asset_duration(
    sender,
    instance: ClipMediaAsset,
    **kwargs,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMediaAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        import ffmpeg
        from pathlib import Path

        from django.conf import settings

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
        # Use queryset.update() to avoid recursive signal dispatch
        ClipMediaAsset.objects.filter(pk=instance.pk).update(duration_sec=duration)
        logger.info(
            "Auto-detected media asset duration",
            extra={"asset_id": str(instance.pk), "duration_sec": duration},
        )
    except Exception as exc:
        logger.warning(
            "Could not auto-detect media asset duration",
            extra={"asset_id": str(instance.pk), "error": str(exc)},
        )


@receiver(post_save, sender=ClipMusicAsset)
def detect_music_asset_duration(
    sender,
    instance: ClipMusicAsset,
    **kwargs,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMusicAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        import ffmpeg
        from pathlib import Path

        from django.conf import settings

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
        ClipMusicAsset.objects.filter(pk=instance.pk).update(duration_sec=duration)
        logger.info(
            "Auto-detected music asset duration",
            extra={"asset_id": str(instance.pk), "duration_sec": duration},
        )
    except Exception as exc:
        logger.warning(
            "Could not auto-detect music asset duration",
            extra={"asset_id": str(instance.pk), "error": str(exc)},
        )


def create_clip_render_template_for_channel(
    sender,
    instance,
    created: bool,
    **kwargs,
) -> None:
    """Auto-create a ClipRenderTemplate when a Channel is first saved.

    Defined as a plain function (not @receiver) because it's connected in
    ClippingConfig.ready() to avoid circular imports (channels ↔ clipping).
    """
    if not created:
        return
    from reelforge.clipping.models import ClipRenderTemplate

    ClipRenderTemplate.objects.get_or_create(channel=instance)
