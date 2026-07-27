"""Tests for server/apps/pipelines/enqueue.py."""

from unittest.mock import patch

import pytest

from server.apps.pipelines.enqueue import (
    kiq_advance_pipeline,
    kiq_execute_stage,
)
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.tasks_api import advance_pipeline, execute_stage
from server.apps.pipelines.tasks_render import execute_render_stage


@pytest.fixture
def enqueue_blueprint() -> PipelineBlueprint:
    return PipelineBlueprint.objects.create(
        name='enqueue_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'research', 'depends_on': [], 'queue': 'api'}]},
    )


@pytest.fixture
def enqueue_channel():
    from server.apps.channels.models import Channel, ChannelKind

    return Channel.objects.create(
        name='Enqueue Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def enqueue_run(
    enqueue_blueprint: PipelineBlueprint,
    enqueue_channel,
) -> PipelineRun:
    return PipelineRun.objects.create(
        channel=enqueue_channel,
        blueprint=enqueue_blueprint,
        blueprint_snapshot=enqueue_blueprint.graph,
        topic='Enqueue test',
    )


@pytest.mark.django_db
def test_kiq_execute_stage_routes_render_queue(
    enqueue_run: PipelineRun,
) -> None:
    execution = StageExecution.objects.create(
        run=enqueue_run,
        stage_key='assembly',
        status=StageStatus.QUEUED,
        queue='render',
    )
    with patch(
        'server.apps.pipelines.enqueue.kiq_render_task',
    ) as render_kiq:
        kiq_execute_stage(str(execution.id))
    render_kiq.assert_called_once_with(execute_render_stage, str(execution.id))


@pytest.mark.django_db
def test_kiq_execute_stage_routes_api_queue(
    enqueue_run: PipelineRun,
) -> None:
    execution = StageExecution.objects.create(
        run=enqueue_run,
        stage_key='research',
        status=StageStatus.QUEUED,
        queue='api',
    )
    with patch(
        'server.apps.pipelines.enqueue.kiq_api_task',
    ) as api_kiq:
        kiq_execute_stage(str(execution.id))
    api_kiq.assert_called_once_with(execute_stage, str(execution.id))


@pytest.mark.django_db
def test_kiq_execute_stage_maps_gpu_to_api(
    enqueue_run: PipelineRun,
) -> None:
    execution = StageExecution.objects.create(
        run=enqueue_run,
        stage_key='alignment',
        status=StageStatus.QUEUED,
        queue='gpu',
    )
    with patch(
        'server.apps.pipelines.enqueue.kiq_api_task',
    ) as api_kiq:
        kiq_execute_stage(str(execution.id))
    api_kiq.assert_called_once_with(execute_stage, str(execution.id))


def test_kiq_advance_pipeline_uses_api_broker() -> None:
    with patch(
        'server.apps.pipelines.enqueue.kiq_api_task',
    ) as api_kiq:
        kiq_advance_pipeline('run-id')
    api_kiq.assert_called_once_with(advance_pipeline, 'run-id')
