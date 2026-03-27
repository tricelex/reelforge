from __future__ import annotations

import pytest

from reelforge.channels.tests.factories import ChannelFactory
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.tests.factories import ClipCandidateFactory
from reelforge.clipping.tests.factories import ClippingJobFactory


@pytest.mark.django_db
def test_layout_config_auto_created_on_candidate_save() -> None:
    candidate = ClipCandidateFactory()
    assert ClipLayoutConfig.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_layout_config_inherits_channel_default_render_mode() -> None:
    channel = ChannelFactory(default_render_mode="CENTER_CROP")
    job = ClippingJobFactory(channel=channel)
    candidate = ClipCandidateFactory(clipping_job=job)
    config = ClipLayoutConfig.objects.get(candidate=candidate)
    assert config.render_mode == "CENTER_CROP"


@pytest.mark.django_db
def test_layout_config_not_duplicated_on_second_save() -> None:
    candidate = ClipCandidateFactory()
    candidate.title = "Updated title"
    candidate.save()
    assert ClipLayoutConfig.objects.filter(candidate=candidate).count() == 1
