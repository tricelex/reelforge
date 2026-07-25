"""Direct service-level tests for ChannelService."""

import pytest


@pytest.mark.django_db
def test_graduation_status_counts_consecutive_clean_completed_runs() -> None:
    """graduation_status counts trailing COMPLETED runs with no manual edits."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
    )

    channel = Channel.objects.create(name='Grad Ch', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='grad_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    for _ in range(3):
        PipelineRun.objects.create(
            channel=channel,
            blueprint=bp,
            blueprint_snapshot={},
            topic='clean',
            status=RunStatus.COMPLETED,
            had_manual_edits=False,
        )
    PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='dirty',
        status=RunStatus.COMPLETED,
        had_manual_edits=True,
    )

    status = ChannelService().graduation_status(str(channel.id))
    assert status.clean_run_count == 3
    assert status.required_count == 10
    assert status.eligible is False


@pytest.mark.django_db
def test_graduation_status_eligible_at_threshold() -> None:
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
    )

    channel = Channel.objects.create(
        name='Grad Ch 2',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='grad_test_v2',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    for _ in range(10):
        PipelineRun.objects.create(
            channel=channel,
            blueprint=bp,
            blueprint_snapshot={},
            topic='clean',
            status=RunStatus.COMPLETED,
            had_manual_edits=False,
        )

    status = ChannelService().graduation_status(str(channel.id))
    assert status.eligible is True


@pytest.mark.django_db
def test_get_assembly_style_creates_defaults() -> None:
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService

    channel = Channel.objects.create(
        name='Get Style Ch',
        kind=ChannelKind.LONGFORM,
    )
    payload = ChannelService().get_assembly_style(str(channel.id))
    assert payload.camera_movements == [
        'push_in',
        'pan_left',
        'pan_right',
        'static_hold',
    ]
    assert payload.transition_styles == ['hard_cut', 'cross_dissolve']
    assert payload.music_bed_gain_db == -18.0


@pytest.mark.django_db
def test_patch_assembly_style_updates_pool() -> None:
    from server.apps.channels.logic.value_objects import (
        AssemblyStyleConfigPatchPayload,
    )
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService

    channel = Channel.objects.create(
        name='Patch Style Ch',
        kind=ChannelKind.LONGFORM,
    )
    result = ChannelService().patch_assembly_style(
        str(channel.id),
        AssemblyStyleConfigPatchPayload(
            camera_movements=['push_in'],
            music_bed_gain_db=-20.0,
        ),
    )
    assert result.camera_movements == ['push_in']
    assert result.music_bed_gain_db == -20.0


@pytest.mark.django_db
def test_patch_assembly_style_empty_payload_is_noop() -> None:
    from server.apps.channels.logic.value_objects import (
        AssemblyStyleConfigPatchPayload,
    )
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService

    channel = Channel.objects.create(
        name='Noop Style Ch',
        kind=ChannelKind.LONGFORM,
    )
    result = ChannelService().patch_assembly_style(
        str(channel.id),
        AssemblyStyleConfigPatchPayload(),
    )
    assert result.camera_movements == []
