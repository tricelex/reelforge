import pytest

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.clips.logic.constants import (
    CandidateStatus,
    CaptionStyle,
    RenderFormat,
    RenderMode,
)
from server.apps.clips.models import (
    ClipCampaign,
    ClipCandidate,
    ClipLayoutConfig,
    ClipPost,
    ClipStyleConfig,
    ClipTimedOverlay,
    ClipTimedSfx,
    Earning,
)
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)


def _create_candidate(pipeline_run: PipelineRun) -> ClipCandidate:
    return ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )


@pytest.fixture
def pipeline_run(db: None) -> PipelineRun:
    channel = Channel.objects.create(
        name='Test Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    blueprint = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='https://www.youtube.com/watch?v=test123',
    )


@pytest.mark.django_db
def test_clip_candidate_creates_configs_on_save(
    pipeline_run: PipelineRun,
) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='Test Clip',
    )
    assert hasattr(candidate, 'layout_config')
    assert hasattr(candidate, 'style_config')
    assert candidate.layout_config.render_mode == RenderMode.SMART_CROP
    assert candidate.style_config.caption_style == CaptionStyle.CHUNKED


@pytest.mark.django_db
def test_clip_candidate_status_default(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='Test Clip',
    )
    assert candidate.status == CandidateStatus.PROPOSED


@pytest.mark.django_db
def test_clip_candidate_duration_property(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    assert candidate.duration_sec == 60.0


@pytest.mark.django_db
def test_clip_layout_config_defaults(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    lc = candidate.layout_config
    assert lc.render_mode == RenderMode.SMART_CROP
    assert lc.render_format == RenderFormat.VERTICAL_9_16
    assert lc.stack_ratio == 0.6


@pytest.mark.django_db
def test_clip_layout_config_has_manual_smart_crop_false(
    pipeline_run: PipelineRun,
) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    assert candidate.layout_config.has_manual_smart_crop is False


@pytest.mark.django_db
def test_clip_layout_config_has_manual_smart_crop_true(
    pipeline_run: PipelineRun,
) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    lc = candidate.layout_config
    lc.manual_crop_x = 100
    lc.manual_crop_y = 200
    lc.manual_crop_w = 300
    lc.manual_crop_h = 400
    assert lc.has_manual_smart_crop is True


@pytest.mark.django_db
def test_clip_layout_config_has_spatial_regions_false(
    pipeline_run: PipelineRun,
) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    assert candidate.layout_config.has_spatial_regions is False


@pytest.mark.django_db
def test_clip_layout_config_has_spatial_regions_true(
    pipeline_run: PipelineRun,
) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    lc = candidate.layout_config
    lc.region_a_x = 0
    lc.region_a_y = 0
    lc.region_a_w = 1920
    lc.region_a_h = 540
    lc.region_b_x = 0
    lc.region_b_y = 540
    lc.region_b_w = 1920
    lc.region_b_h = 540
    assert lc.has_spatial_regions is True


@pytest.mark.django_db
def test_clip_style_config_defaults(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    sc = candidate.style_config
    assert sc.caption_enabled is True
    assert sc.caption_style == CaptionStyle.CHUNKED
    assert sc.hook_enabled is True
    assert sc.watermark_enabled is False


@pytest.mark.django_db
def test_clip_timed_overlay_str(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        text='Hello',
        start_sec=5.0,
        end_sec=10.0,
    )
    assert 'Hello' in str(overlay)


@pytest.mark.django_db
def test_clip_candidate_str(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='Test Clip',
    )
    assert 'Test Clip' in str(candidate)


@pytest.mark.django_db
def test_clip_layout_config_str(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    assert 'SMART_CROP' in str(candidate.layout_config)


@pytest.mark.django_db
def test_clip_style_config_str(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    assert 'Style' in str(candidate.style_config)


@pytest.mark.django_db
def test_clip_post_str(pipeline_run: PipelineRun) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    post = ClipPost.objects.create(
        candidate=candidate,
        platform='youtube',
    )
    assert 'youtube' in str(post)


@pytest.mark.django_db
def test_signal_does_not_duplicate_configs_on_update(
    pipeline_run: PipelineRun,
) -> None:
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='T',
    )
    # Save again (update, not create) — should not raise or duplicate configs
    candidate.title = 'Updated'
    candidate.save(update_fields=['title'])
    assert ClipLayoutConfig.objects.filter(candidate=candidate).count() == 1
    assert ClipStyleConfig.objects.filter(candidate=candidate).count() == 1


@pytest.mark.django_db
def test_clip_campaign_str(pipeline_run: PipelineRun) -> None:
    """ClipCampaign.__str__ returns the campaign name."""
    campaign = ClipCampaign.objects.create(
        channel=pipeline_run.channel,
        name='Summer clips',
    )
    assert str(campaign) == 'Summer clips'


@pytest.mark.django_db
def test_earning_str(pipeline_run: PipelineRun) -> None:
    """Earning.__str__ includes platform and campaign."""
    campaign = ClipCampaign.objects.create(
        channel=pipeline_run.channel,
        name='Earnings batch',
    )
    earning = Earning.objects.create(
        campaign=campaign,
        platform='youtube',
        recorded_at='2026-06-19T12:00:00+00:00',
    )
    text = str(earning)
    assert 'youtube' in text
    assert 'Earnings batch' in text


@pytest.mark.django_db
def test_clip_style_config_new_field_defaults(pipeline_run: PipelineRun) -> None:
    candidate = _create_candidate(pipeline_run)
    config = ClipStyleConfig.objects.get(candidate=candidate)

    assert config.watermark_color == '#FFFFFF'
    assert config.watermark_font == 'MONTSERRAT_BOLD'
    assert config.watermark_font_asset is None
    assert config.caption_font_asset is None
    assert config.hook_font_asset is None
    assert config.intro_transition_duration_sec == 0.5
    assert config.outro_transition_duration_sec == 0.5
    assert config.intro_transition_asset is None
    assert config.outro_transition_asset is None
    assert config.hook_animation == 'NONE'
    assert config.caption_highlight_color == '#FFD400'
    assert config.caption_uppercase is False
    assert config.color_filter == 'NONE'
    assert config.brightness == 0.0
    assert config.contrast == 0.0
    assert config.saturation == 0.0
    assert config.lut_asset is None
    assert config.playback_speed == 1.0
    assert config.caption_font == 'MONTSERRAT_BOLD'
    assert config.hook_font == 'MONTSERRAT_BOLD'


@pytest.mark.django_db
def test_clip_layout_config_fit_mode_default(pipeline_run: PipelineRun) -> None:
    candidate = _create_candidate(pipeline_run)
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    assert layout.fit_mode == 'CROP'


@pytest.mark.django_db
def test_clip_timed_overlay_new_field_defaults(pipeline_run: PipelineRun) -> None:
    candidate = _create_candidate(pipeline_run)
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        start_sec=0.0,
        end_sec=1.0,
    )
    assert overlay.font == 'MONTSERRAT_BOLD'
    assert overlay.font_asset is None
    assert overlay.width is None
    assert overlay.animation == 'NONE'
    assert overlay.video_asset is None
    assert overlay.shape == 'RECTANGLE'


@pytest.mark.django_db
def test_clip_timed_sfx_creation(pipeline_run: PipelineRun) -> None:
    from django.core.files.base import ContentFile

    from server.apps.assets.models import LibraryAsset, LibraryAssetKind

    candidate = _create_candidate(pipeline_run)
    sfx_asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.SFX,
        name='whoosh.mp3',
        file=ContentFile(b'audio', name='whoosh.mp3'),
    )
    sfx = ClipTimedSfx.objects.create(
        candidate=candidate,
        sfx_asset=sfx_asset,
        start_sec=5.0,
    )
    assert sfx.volume_db == 0.0
    assert str(sfx) == f'SFX {sfx_asset.name} @5.0s'
