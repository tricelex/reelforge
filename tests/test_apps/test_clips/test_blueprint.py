"""Tests for the clipping_v1 PipelineBlueprint data migration functions."""

import importlib

import pytest


@pytest.mark.django_db
def test_clipping_v1_blueprint_migration() -> None:
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    mig = importlib.import_module(
        'server.apps.pipelines.migrations.0003_add_clipping_v1_blueprint',
    )

    class _FakeApps:
        def get_model(self, app: str, model: str) -> type:
            return PipelineBlueprint  # type: ignore[return-value]

    # Clean slate — may have been pre-created by migration run or a prior test
    PipelineBlueprint.objects.filter(name='clipping_v1').delete()

    mig._add_blueprint(_FakeApps(), None)

    bp = PipelineBlueprint.objects.get(name='clipping_v1')
    assert bp.kind == PipelineKind.CLIPPING
    assert bp.is_active is True
    stage_keys = [s['key'] for s in bp.graph['stages']]
    assert stage_keys == [
        'clip_ingest',
        'clip_transcribe',
        'clip_analyze',
        'clip_approval_gate',
        'clip_render',
        'clip_distribute',
    ]
    gate_node = next(
        s for s in bp.graph['stages'] if s['key'] == 'clip_approval_gate'
    )
    assert gate_node.get('gate') is True

    # Also verify _remove_blueprint cleans up (covers migration lines 34-36)
    mig._remove_blueprint(_FakeApps(), None)
    assert not PipelineBlueprint.objects.filter(name='clipping_v1').exists()
