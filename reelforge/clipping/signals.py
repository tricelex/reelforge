from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver
from django_fsm.signals import post_transition

from reelforge.clipping.constants import PLATFORM_RENDER_MODE_DEFAULTS
from reelforge.clipping.constants import RenderMode
from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClipMediaAsset
from reelforge.clipping.models import ClipMusicAsset
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipRenderTemplate
from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.clipping")


def on_clipping_job_transition(
    sender: type,
    instance: ClippingJob,
    name: str,
    source: str,
    target: str,
    **kwargs: Any,
) -> None:
    """Log ClippingJob FSM failures."""
    if target == ClippingJob.Status.FAILED:
        logger.error(
            "ClippingJob failed",
            extra={"clipping_job_id": str(instance.id), "last_error": instance.last_error},
        )


post_transition.connect(on_clipping_job_transition, sender=ClippingJob)


@receiver(post_save, sender=ClipCandidate)
def create_layout_config_for_candidate(
    sender: type,
    instance: ClipCandidate,
    created: bool,
    **kwargs: Any,
) -> None:
    """Auto-create a ClipLayoutConfig when a ClipCandidate is first saved.

    Uses the social account's platform to pick the default render mode.
    """
    if not created:
        return
    platform = instance.clipping_job.social_account.platform
    render_mode = PLATFORM_RENDER_MODE_DEFAULTS.get(platform, RenderMode.SMART_CROP)
    ClipLayoutConfig.objects.get_or_create(
        candidate=instance,
        defaults={"render_mode": render_mode},
    )


@receiver(post_save, sender=ClipCandidate)
def create_style_config_for_candidate(
    sender: type,
    instance: ClipCandidate,
    created: bool,
    **kwargs: Any,
) -> None:
    """Auto-create a ClipStyleConfig when a ClipCandidate is first saved.

    Pre-populates from the global default ClipRenderTemplate.
    """
    if not created:
        return
    template = ClipRenderTemplate.objects.filter(is_default=True).first()
    if template is None:
        template = ClipRenderTemplate.objects.first()
    style_defaults = template.to_style_defaults() if template is not None else {}
    ClipStyleConfig.objects.get_or_create(
        candidate=instance,
        defaults={**style_defaults, "render_template": template},
    )


@receiver(post_save, sender=ClipMediaAsset)
def detect_media_asset_duration(
    sender: type,
    instance: ClipMediaAsset,
    **kwargs: Any,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMediaAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        from pathlib import Path

        import ffmpeg
        from django.conf import settings

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
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
    sender: type,
    instance: ClipMusicAsset,
    **kwargs: Any,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMusicAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        from pathlib import Path

        import ffmpeg
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
