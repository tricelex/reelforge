from __future__ import annotations

import pytest
from django_fsm import TransitionNotAllowed

from reelforge.clipping.constants import CaptionStyle
from reelforge.clipping.constants import HookStyle
from reelforge.clipping.constants import TransitionStyle
from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClipMediaAsset
from reelforge.clipping.models import ClipMusicAsset
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipRenderStageResult
from reelforge.clipping.models import ClipRenderTemplate
from reelforge.clipping.models import ClipStyleConfig
from reelforge.clipping.models import ClipTimedOverlay
from reelforge.clipping.tests.factories import ClipCandidateFactory
from reelforge.clipping.tests.factories import ClippingJobFactory
from reelforge.clipping.tests.factories import ClipRenderFactory


def test_caption_style_choices_exist() -> None:
    assert CaptionStyle.WORD_BY_WORD == "WORD_BY_WORD"
    assert CaptionStyle.CHUNKED == "CHUNKED"
    assert CaptionStyle.LOWER_THIRD == "LOWER_THIRD"
    assert CaptionStyle.EMOJI_ACCENT == "EMOJI_ACCENT"


def test_transition_style_choices_exist() -> None:
    assert TransitionStyle.NONE == "NONE"
    assert TransitionStyle.CROSSFADE == "CROSSFADE"
    assert TransitionStyle.FADE_BLACK == "FADE_BLACK"
    assert TransitionStyle.WIPE_LEFT == "WIPE_LEFT"
    assert TransitionStyle.WIPE_RIGHT == "WIPE_RIGHT"


def test_hook_style_choices_exist() -> None:
    assert HookStyle.TITLE_CARD == "TITLE_CARD"
    assert HookStyle.OVERLAY_TOP == "OVERLAY_TOP"
    assert HookStyle.OVERLAY_CENTER == "OVERLAY_CENTER"


@pytest.mark.django_db
def test_clipping_job_initial_status() -> None:
    job = ClippingJobFactory()
    assert job.status == ClippingJob.Status.INITIALIZING


@pytest.mark.django_db
def test_clipping_job_begin_download_transition() -> None:
    job = ClippingJobFactory()
    job.begin_download()
    job.save(update_fields=["status", "updated_at"])
    job.refresh_from_db()
    assert job.status == ClippingJob.Status.DOWNLOADING


@pytest.mark.django_db
def test_clipping_job_cannot_skip_states() -> None:
    job = ClippingJobFactory()
    with pytest.raises(TransitionNotAllowed):
        job.begin_transcription()


@pytest.mark.django_db
def test_clipping_job_mark_failed_from_any_state() -> None:
    job = ClippingJobFactory()
    job.begin_download()
    job.save(update_fields=["status", "updated_at"])
    job.mark_failed(error="Test error")
    job.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
    assert job.status == ClippingJob.Status.FAILED
    assert job.last_error == "Test error"


@pytest.mark.django_db
def test_clip_candidate_duration_too_short_raises() -> None:
    job = ClippingJobFactory()
    candidate = ClipCandidate(
        clipping_job=job,
        start_sec=0.0,
        end_sec=20.0,
        title="Short clip",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    with pytest.raises(Exception, match="30"):
        candidate.full_clean()


@pytest.mark.django_db
def test_clip_candidate_duration_too_long_raises() -> None:
    job = ClippingJobFactory()
    candidate = ClipCandidate(
        clipping_job=job,
        start_sec=0.0,
        end_sec=200.0,
        title="Long clip",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    with pytest.raises(Exception, match="180"):
        candidate.full_clean()


@pytest.mark.django_db
def test_clip_candidate_overlap_detection() -> None:
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job, start_sec=0.0, end_sec=60.0)
    overlapping = ClipCandidate(
        clipping_job=job,
        start_sec=30.0,
        end_sec=90.0,
        title="Overlapping",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    with pytest.raises(Exception, match="overlaps"):
        overlapping.full_clean()


@pytest.mark.django_db
def test_clip_candidate_no_overlap_different_jobs() -> None:
    job1 = ClippingJobFactory()
    job2 = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job1, start_sec=0.0, end_sec=60.0)
    # Same timestamps but different job — should NOT raise
    candidate = ClipCandidate(
        clipping_job=job2,
        start_sec=0.0,
        end_sec=60.0,
        title="No overlap",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    candidate.full_clean()  # Should not raise


@pytest.mark.django_db
def test_clip_candidate_duration_property() -> None:
    candidate = ClipCandidateFactory(start_sec=30.0, end_sec=90.0)
    assert candidate.duration_sec == 60.0


@pytest.mark.django_db
def test_clip_layout_config_default_render_mode() -> None:
    from reelforge.channels.models import SocialAccount
    from reelforge.channels.tests.factories import SocialAccountFactory

    # YOUTUBE platform maps to CENTER_CROP per PLATFORM_RENDER_MODE_DEFAULTS
    social_account = SocialAccountFactory(platform=SocialAccount.Platform.YOUTUBE)
    from reelforge.clipping.tests.factories import ClippingJobFactory as _JobFactory

    job = _JobFactory(social_account=social_account)
    candidate = ClipCandidateFactory(clipping_job=job)
    config = ClipLayoutConfig.objects.get(candidate=candidate)
    assert config.render_mode == "CENTER_CROP"


@pytest.mark.django_db
def test_has_manual_smart_crop_true_when_all_fields_set() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=405,
        manual_crop_h=720,
    )
    assert config.has_manual_smart_crop is True


@pytest.mark.django_db
def test_has_manual_smart_crop_false_when_any_field_null() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=None,
        manual_crop_h=720,
    )
    assert config.has_manual_smart_crop is False


@pytest.mark.django_db
def test_has_spatial_regions_true_when_all_ab_fields_set() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
        region_b_x=880, region_b_y=420, region_b_w=400, region_b_h=300,
    )
    assert config.has_spatial_regions is True


@pytest.mark.django_db
def test_has_spatial_regions_false_when_region_b_missing() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
    )
    assert config.has_spatial_regions is False


@pytest.mark.django_db
def test_clip_render_template_auto_fields_have_correct_defaults() -> None:
    template = ClipRenderTemplate.objects.create(name="Test Template")
    assert template.caption_enabled is True
    assert template.caption_style == "CHUNKED"
    assert template.caption_font == "Montserrat-Bold"
    assert template.caption_size == 52
    assert template.caption_color == "#FFFFFF"
    assert template.caption_stroke_color == "#000000"
    assert template.caption_stroke_width == 3
    assert template.caption_bg_color == ""
    assert template.caption_position == "BOTTOM"
    assert template.caption_animation == "POP"
    assert template.caption_language == "en"
    assert template.caption_translate_to == ""
    assert template.emoji_keyword_map == {}
    assert template.hook_enabled is True
    assert template.hook_style == "OVERLAY_TOP"
    assert template.hook_duration_sec == 2.5
    assert template.hook_font == "Montserrat-Bold"
    assert template.hook_size == 60
    assert template.hook_color == "#FFFFFF"
    assert template.hook_bg_color == "#CC000000"
    assert template.hook_animation == "FADE"
    assert template.intro_transition == "NONE"
    assert template.outro_transition == "NONE"
    assert template.transition_duration_sec == 0.5
    assert template.watermark_enabled is False
    assert template.watermark_type == "TEXT"
    assert template.watermark_text == ""
    assert template.watermark_position == "BOTTOM_RIGHT"
    assert template.watermark_opacity == 0.6
    assert template.watermark_size == 32
    assert template.progress_bar_enabled is False
    assert template.progress_bar_position == "TOP"
    assert template.progress_bar_color == "#FFFFFF"
    assert template.progress_bar_height == 6
    assert template.music_enabled is False
    assert template.music_volume_db == -20.0
    assert template.music_fade_in_sec == 1.0
    assert template.music_fade_out_sec == 1.0


@pytest.mark.django_db
def test_clip_render_template_to_style_defaults_returns_all_style_fields() -> None:
    template = ClipRenderTemplate.objects.create(name="Test Template")
    template.caption_size = 72
    template.music_enabled = True
    template.save(update_fields=["caption_size", "music_enabled", "updated_at"])
    defaults = template.to_style_defaults()
    assert defaults["caption_size"] == 72
    assert defaults["music_enabled"] is True
    assert "channel" not in defaults
    assert "id" not in defaults
    assert "created_at" not in defaults


@pytest.mark.django_db
def test_clip_media_asset_str_includes_name_and_type() -> None:
    asset = ClipMediaAsset.objects.create(name="Brand Intro", asset_type="INTRO")
    assert "Brand Intro" in str(asset)
    assert "INTRO" in str(asset) or "Intro" in str(asset)


@pytest.mark.django_db
def test_clip_music_asset_str_includes_name() -> None:
    asset = ClipMusicAsset.objects.create(name="Chill Beat")
    assert "Chill Beat" in str(asset)


@pytest.mark.django_db
def test_clip_style_config_has_all_style_fields() -> None:
    candidate = ClipCandidateFactory()
    style_config, _ = ClipStyleConfig.objects.get_or_create(candidate=candidate)
    assert hasattr(style_config, "caption_enabled")
    assert hasattr(style_config, "music_volume_db")
    assert hasattr(style_config, "intro_asset")
    assert hasattr(style_config, "outro_asset")
    assert hasattr(style_config, "music_asset")
    assert hasattr(style_config, "translated_transcript_json")
    assert hasattr(style_config, "preview_image")


@pytest.mark.django_db
def test_clip_timed_overlay_clean_validates_end_after_start() -> None:
    from django.core.exceptions import ValidationError

    candidate = ClipCandidateFactory()
    overlay = ClipTimedOverlay(
        candidate=candidate,
        overlay_type="TEXT",
        text="hello",
        start_sec=10.0,
        end_sec=5.0,
    )
    with pytest.raises(ValidationError):
        overlay.clean()


@pytest.mark.django_db
def test_clip_timed_overlay_clean_passes_with_valid_times() -> None:
    candidate = ClipCandidateFactory()
    overlay = ClipTimedOverlay(
        candidate=candidate,
        overlay_type="TEXT",
        text="hello",
        start_sec=5.0,
        end_sec=10.0,
    )
    overlay.clean()  # should not raise


@pytest.mark.django_db
def test_clip_style_config_factory_handles_signal_conflict() -> None:
    """Factory must not fail even when the signal already created a ClipStyleConfig."""
    from reelforge.clipping.tests.factories import ClipStyleConfigFactory

    config = ClipStyleConfigFactory()
    assert config.pk is not None
    assert ClipStyleConfig.objects.filter(candidate=config.candidate).count() == 1


@pytest.mark.django_db
def test_clip_media_asset_factory_creates_valid_record() -> None:
    from reelforge.clipping.tests.factories import ClipMediaAssetFactory

    asset = ClipMediaAssetFactory()
    assert asset.pk is not None
    assert asset.asset_type == "INTRO"


@pytest.mark.django_db
def test_clip_render_stage_result_str() -> None:
    render = ClipRenderFactory()
    result = ClipRenderStageResult.objects.create(
        render=render,
        stage_name="trim_and_crop",
        stage_order=1,
        status=ClipRenderStageResult.Status.COMPLETED,
    )
    assert "trim_and_crop" in str(result)
    assert "1" in str(result)


@pytest.mark.django_db
def test_clip_layout_config_str() -> None:
    from reelforge.channels.models import SocialAccount
    from reelforge.channels.tests.factories import SocialAccountFactory

    # TIKTOK platform maps to SMART_CROP
    social_account = SocialAccountFactory(platform=SocialAccount.Platform.TIKTOK)
    from reelforge.clipping.tests.factories import ClippingJobFactory as _JobFactory

    job = _JobFactory(social_account=social_account)
    candidate = ClipCandidateFactory(clipping_job=job)
    config = ClipLayoutConfig.objects.get(candidate=candidate)
    assert "Smart Crop" in str(config)
