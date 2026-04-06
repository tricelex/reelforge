from __future__ import annotations

import pytest
from ***REMOVED***.channels.tests.factories import SocialAccountFactory
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory, ClippingJobFactory
from ***REMOVED***.clipping.constants import PLATFORM_RENDER_MODE_DEFAULTS


@pytest.mark.django_db
def test_layout_config_uses_tiktok_smart_crop():
    account = SocialAccountFactory(platform="TIKTOK")
    job = ClippingJobFactory(social_account=account)
    candidate = ClipCandidateFactory(clipping_job=job)
    assert candidate.layout_config.render_mode == "SMART_CROP"


@pytest.mark.django_db
def test_layout_config_uses_youtube_center_crop():
    account = SocialAccountFactory(platform="YOUTUBE")
    job = ClippingJobFactory(social_account=account)
    candidate = ClipCandidateFactory(clipping_job=job)
    assert candidate.layout_config.render_mode == "CENTER_CROP"


@pytest.mark.django_db
def test_style_config_seeded_from_default_template():
    """ClipStyleConfig is auto-created and render_template points to default."""
    account = SocialAccountFactory(platform="TIKTOK")
    job = ClippingJobFactory(social_account=account)
    candidate = ClipCandidateFactory(clipping_job=job)
    assert candidate.style_config is not None
    from ***REMOVED***.clipping.models import ClipRenderTemplate
    default = ClipRenderTemplate.objects.filter(is_default=True).first()
    assert candidate.style_config.render_template == default
