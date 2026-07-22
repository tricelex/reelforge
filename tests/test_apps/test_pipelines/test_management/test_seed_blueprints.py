import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_seed_blueprints_creates_clipping_v1() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='clipping_v1')
    assert bp.kind == 'CLIPPING'
    keys = {s['key'] for s in bp.graph['stages']}
    assert keys == {
        'clip_ingest',
        'clip_transcribe',
        'clip_analyze',
        'clip_approval_gate',
        'clip_render',
        'clip_distribute',
    }


def test_seed_blueprints_creates_clipping_v1_manual() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='clipping_v1_manual')
    assert bp.kind == 'CLIPPING'
    keys = {s['key'] for s in bp.graph['stages']}
    assert keys == {
        'clip_ingest',
        'clip_transcribe',
        'clip_manual_setup',
        'clip_approval_gate',
        'clip_render',
        'clip_distribute',
    }


def test_seed_blueprints_is_idempotent_on_rerun() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    call_command('seed_blueprints')
    assert PipelineBlueprint.objects.filter(name='clipping_v1').count() == 1
    assert (
        PipelineBlueprint.objects.filter(name='clipping_v1_manual').count() == 1
    )


def test_seed_blueprints_still_creates_longform_v1() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    assert PipelineBlueprint.objects.filter(name='longform_v1').exists()


def test_longform_v1_graph_includes_narrative_qc_between_breakdown_and_visuals() -> (
    None
):
    from server.apps.pipelines.management.commands.seed_blueprints import (
        _LONGFORM_V1_GRAPH,
    )

    stages: list[dict[str, object]] = _LONGFORM_V1_GRAPH['stages']  # type: ignore[assignment]
    by_key = {node['key']: node for node in stages}
    assert by_key['script_gate']['depends_on'] == ['scene_breakdown']
    assert by_key['script_gate'].get('gate') is True
    assert by_key['narrative_qc']['depends_on'] == ['script_gate']
    assert by_key['cast_proposal']['depends_on'] == ['scene_breakdown']
    assert by_key['character_gate']['depends_on'] == [
        'cast_proposal',
        'narrative_qc',
    ]
    assert by_key['character_gate'].get('gate') is True
    assert by_key['visual_prompts']['depends_on'] == ['character_gate']
    assert by_key['storyboard_gate']['depends_on'] == ['image_gen']
    assert by_key['storyboard_gate'].get('gate') is True
    assert by_key['tts']['depends_on'] == ['storyboard_gate']
    assert by_key['motion']['depends_on'] == ['storyboard_gate']
    assert by_key['music_plan']['depends_on'] == ['narrative_qc']
    assert by_key['final_gate']['depends_on'] == [
        'qc',
        'thumbnail',
        'metadata',
    ]
    assert by_key['final_gate'].get('gate') is True
    assert by_key['publish']['depends_on'] == ['final_gate']
    assert by_key['metadata']['depends_on'] == ['script', 'alignment']
    assert by_key['thumbnail']['depends_on'] == ['metadata']
