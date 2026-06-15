import pytest

from server.apps.clips.logic.constants import (
    CandidateStatus,
    CaptionStyle,
    RenderFormat,
    RenderMode,
)
from server.apps.clips.models import (
    ClipCandidate,
    ClipLayoutConfig,
    ClipStyleConfig,
    ClipTimedOverlay,
)


@pytest.fixture()
def pipeline_run(db):  # type: ignore[no-untyped-def]
    from server.apps.channels.models import Channel, ChannelKind, PublishMode
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

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
def test_clip_candidate_creates_configs_on_save(pipeline_run) -> None:  # type: ignore[no-untyped-def]
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
def test_clip_candidate_status_default(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run,
        start_sec=10.0,
        end_sec=70.0,
        title='Test Clip',
    )
    assert candidate.status == CandidateStatus.PROPOSED


@pytest.mark.django_db
def test_clip_candidate_duration_property(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    assert candidate.duration_sec == 60.0


@pytest.mark.django_db
def test_clip_layout_config_defaults(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    lc = candidate.layout_config
    assert lc.render_mode == RenderMode.SMART_CROP
    assert lc.render_format == RenderFormat.VERTICAL_9_16
    assert lc.stack_ratio == 0.6


@pytest.mark.django_db
def test_clip_layout_config_has_manual_smart_crop_false(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    assert candidate.layout_config.has_manual_smart_crop is False


@pytest.mark.django_db
def test_clip_layout_config_has_manual_smart_crop_true(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    lc = candidate.layout_config
    lc.manual_crop_x = 100
    lc.manual_crop_y = 200
    lc.manual_crop_w = 300
    lc.manual_crop_h = 400
    assert lc.has_manual_smart_crop is True


@pytest.mark.django_db
def test_clip_layout_config_has_spatial_regions_false(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    assert candidate.layout_config.has_spatial_regions is False


@pytest.mark.django_db
def test_clip_layout_config_has_spatial_regions_true(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
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
def test_clip_style_config_defaults(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    sc = candidate.style_config
    assert sc.caption_enabled is True
    assert sc.caption_style == CaptionStyle.CHUNKED
    assert sc.hook_enabled is True
    assert sc.watermark_enabled is False


@pytest.mark.django_db
def test_clip_timed_overlay_str(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        text='Hello',
        start_sec=5.0,
        end_sec=10.0,
    )
    assert 'Hello' in str(overlay)


@pytest.mark.django_db
def test_clip_candidate_str(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='Test Clip',
    )
    assert 'Test Clip' in str(candidate)


@pytest.mark.django_db
def test_clip_layout_config_str(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    assert 'SMART_CROP' in str(candidate.layout_config)


@pytest.mark.django_db
def test_clip_style_config_str(pipeline_run) -> None:  # type: ignore[no-untyped-def]
    candidate = ClipCandidate.objects.create(
        run=pipeline_run, start_sec=10.0, end_sec=70.0, title='T',
    )
    assert 'Style' in str(candidate.style_config)
