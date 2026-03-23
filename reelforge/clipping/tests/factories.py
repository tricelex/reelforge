from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from reelforge.channels.tests.factories import ChannelFactory
from reelforge.channels.tests.factories import SocialAccountFactory
from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipPost
from reelforge.clipping.models import ClipRender
from reelforge.clipping.models import ClippingJob


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
