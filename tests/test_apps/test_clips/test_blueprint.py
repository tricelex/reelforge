"""Tests that the clipping_v1 PipelineBlueprint data migration ran correctly."""

import pytest


@pytest.mark.django_db
def test_clipping_v1_blueprint_exists() -> None:
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

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
    gate_node = next(s for s in bp.graph['stages'] if s['key'] == 'clip_approval_gate')
    assert gate_node.get('gate') is True
