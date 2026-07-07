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
        name='grad_test_v1', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )
    for _ in range(3):
        PipelineRun.objects.create(
            channel=channel, blueprint=bp, blueprint_snapshot={}, topic='clean',
            status=RunStatus.COMPLETED, had_manual_edits=False,
        )
    PipelineRun.objects.create(
        channel=channel, blueprint=bp, blueprint_snapshot={}, topic='dirty',
        status=RunStatus.COMPLETED, had_manual_edits=True,
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

    channel = Channel.objects.create(name='Grad Ch 2', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='grad_test_v2', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )
    for _ in range(10):
        PipelineRun.objects.create(
            channel=channel, blueprint=bp, blueprint_snapshot={}, topic='clean',
            status=RunStatus.COMPLETED, had_manual_edits=False,
        )

    status = ChannelService().graduation_status(str(channel.id))
    assert status.eligible is True
