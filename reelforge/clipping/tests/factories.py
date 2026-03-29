from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from ***REMOVED***.channels.tests.factories import ChannelFactory
from ***REMOVED***.channels.tests.factories import SocialAccountFactory
from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderStageResult
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay


class ClippingJobFactory(DjangoModelFactory[ClippingJob]):
    channel = factory.SubFactory(ChannelFactory)
    source_type = ClippingJob.SourceType.YOUTUBE_URL
    source_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    source_title = factory.Sequence(lambda n: f"Test Video {n}")
    clips_requested = 3

    class Meta:
        model = ClippingJob


class ClipCandidateFactory(DjangoModelFactory[ClipCandidate]):
    clipping_job = factory.SubFactory(ClippingJobFactory)
    start_sec = 60.0
    end_sec = 120.0
    title = "Amazing clip title"
    hook_text = "You won't believe this"
    caption_template = "{title} \U0001f3af"
    relevance_score = 8.5
    reason = "High engagement moment"
    transcript_excerpt = "Sample transcript text here"

    class Meta:
        model = ClipCandidate


class ClipRenderFactory(DjangoModelFactory[ClipRender]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    format = ClipRender.Format.VERTICAL_9_16
    include_captions = True
    include_title_card = True
    include_branding = True

    class Meta:
        model = ClipRender


class ClipPostFactory(DjangoModelFactory[ClipPost]):
    render = factory.SubFactory(ClipRenderFactory)
    social_account = factory.SubFactory(SocialAccountFactory)
    caption = "Test caption #shorts"
    title = "Test Short"

    class Meta:
        model = ClipPost


class ClipLayoutConfigFactory(DjangoModelFactory[ClipLayoutConfig]):
    """Factory for ClipLayoutConfig.

    Uses update_or_create so it works even when the auto-creation signal
    has already created a ClipLayoutConfig for the candidate.
    """

    candidate = factory.SubFactory(ClipCandidateFactory)
    render_mode = ClipLayoutConfig.RenderMode.SMART_CROP

    class Meta:
        model = ClipLayoutConfig

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        candidate = kwargs.get("candidate")
        if candidate is not None:
            obj, _ = model_class.objects.update_or_create(
                candidate=candidate,
                defaults={k: v for k, v in kwargs.items() if k != "candidate"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipRenderTemplateFactory(DjangoModelFactory[ClipRenderTemplate]):
    """Factory for ClipRenderTemplate.

    Uses update_or_create because the Channel post_save signal auto-creates one.
    """

    channel = factory.SubFactory(ChannelFactory)

    class Meta:
        model = ClipRenderTemplate

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        channel = kwargs.get("channel")
        if channel is not None:
            obj, _ = model_class.objects.update_or_create(
                channel=channel,
                defaults={k: v for k, v in kwargs.items() if k != "channel"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipMediaAssetFactory(DjangoModelFactory[ClipMediaAsset]):
    channel = factory.SubFactory(ChannelFactory)
    asset_type = "INTRO"
    name = factory.Sequence(lambda n: f"Intro Clip {n}")
    file = factory.django.FileField(filename="intro.mp4", data=b"fake")
    is_active = True

    class Meta:
        model = ClipMediaAsset


class ClipMusicAssetFactory(DjangoModelFactory[ClipMusicAsset]):
    channel = factory.SubFactory(ChannelFactory)
    name = factory.Sequence(lambda n: f"Music Track {n}")
    file = factory.django.FileField(filename="track.mp3", data=b"fake")
    genre = "Chill"
    is_active = True

    class Meta:
        model = ClipMusicAsset


class ClipStyleConfigFactory(DjangoModelFactory[ClipStyleConfig]):
    """Factory for ClipStyleConfig.

    Uses update_or_create because the ClipCandidate post_save signal auto-creates one.
    """

    candidate = factory.SubFactory(ClipCandidateFactory)

    class Meta:
        model = ClipStyleConfig

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        candidate = kwargs.get("candidate")
        if candidate is not None:
            obj, _ = model_class.objects.update_or_create(
                candidate=candidate,
                defaults={k: v for k, v in kwargs.items() if k != "candidate"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipTimedOverlayFactory(DjangoModelFactory[ClipTimedOverlay]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    overlay_type = ClipTimedOverlay.OverlayType.TEXT
    text = "Test overlay text"
    start_sec = 5.0
    end_sec = 10.0

    class Meta:
        model = ClipTimedOverlay


class ClipRenderStageResultFactory(DjangoModelFactory[ClipRenderStageResult]):
    render = factory.SubFactory(ClipRenderFactory)
    stage_name = "trim_and_crop"
    stage_order = 1
    status = ClipRenderStageResult.Status.PENDING

    class Meta:
        model = ClipRenderStageResult
