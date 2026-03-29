from __future__ import annotations

import pytest

from ***REMOVED***.channels.tests.factories import ChannelFactory
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClippingJobFactory


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


@pytest.mark.django_db
def test_clip_render_template_auto_created_on_channel_save() -> None:
    channel = ChannelFactory()
    assert ClipRenderTemplate.objects.filter(channel=channel).exists()


@pytest.mark.django_db
def test_clip_render_template_not_duplicated_on_second_channel_save() -> None:
    channel = ChannelFactory()
    channel.name = "Updated Name"
    channel.save()
    assert ClipRenderTemplate.objects.filter(channel=channel).count() == 1


@pytest.mark.django_db
def test_clip_style_config_auto_created_on_candidate_save() -> None:
    candidate = ClipCandidateFactory()
    assert ClipStyleConfig.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_clip_style_config_inherits_template_values() -> None:
    channel = ChannelFactory()
    template = ClipRenderTemplate.objects.get(channel=channel)
    template.caption_size = 72
    template.music_enabled = True
    template.save(update_fields=["caption_size", "music_enabled", "updated_at"])

    job = ClippingJobFactory(channel=channel)
    candidate = ClipCandidateFactory(clipping_job=job)
    style_config = ClipStyleConfig.objects.get(candidate=candidate)
    assert style_config.caption_size == 72
    assert style_config.music_enabled is True


@pytest.mark.django_db
def test_clip_style_config_not_duplicated_on_second_candidate_save() -> None:
    candidate = ClipCandidateFactory()
    candidate.title = "New title"
    candidate.save()
    assert ClipStyleConfig.objects.filter(candidate=candidate).count() == 1
