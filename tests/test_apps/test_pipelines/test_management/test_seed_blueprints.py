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


def test_seed_blueprints_creates_all_four_editor_blueprints() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    names = {
        'longform_editor_v1',
        'longform_doc_editor_v1',
        'clipping_editor_v1',
        'clipping_editor_manual_v1',
    }
    for name in names:
        bp = PipelineBlueprint.objects.get(name=name)
        assert bp.is_active
        assert bp.graph.get('handoff') == 'editor_package'


def test_longform_editor_v1_has_package_zip_no_assembly_or_publish() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_editor_v1')
    keys = {s['key'] for s in bp.graph['stages']}
    assert 'package_zip' in keys
    assert 'editor_brief' in keys
    assert 'timeline_export' in keys
    assert 'caption_bundle' in keys
    assert 'assembly' not in keys
    assert 'qc' not in keys
    assert 'final_gate' not in keys
    assert 'publish' not in keys
    assert 'visual_anchors' in keys
    by_key = {s['key']: s for s in bp.graph['stages']}
    assert by_key['image_gen']['depends_on'] == ['visual_anchors']
    assert by_key['scene_breakdown']['config']['min_words'] == 8


def test_longform_scene_export_v1_ends_at_scene_breakdown() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_scene_export_v1')
    assert bp.is_active
    assert bp.graph.get('handoff') == 'editor_package'
    keys = {s['key'] for s in bp.graph['stages']}
    by_key = {s['key']: s for s in bp.graph['stages']}
    assert keys == {
        'research',
        'outline',
        'script',
        'scene_breakdown',
        'script_gate',
        'editor_brief',
        'metadata',
        'timeline_export',
        'caption_bundle',
        'package_zip',
    }
    assert by_key['script_gate']['depends_on'] == ['scene_breakdown']
    assert by_key['script_gate'].get('gate') is True
    assert by_key['editor_brief']['depends_on'] == ['script_gate']
    assert by_key['metadata']['depends_on'] == ['editor_brief']
    assert by_key['timeline_export']['depends_on'] == ['metadata']
    assert by_key['package_zip']['depends_on'] == ['caption_bundle']
    assert by_key['scene_breakdown']['config']['min_words'] == 8


def test_clipping_editor_v1_skips_preview_and_distribute() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='clipping_editor_v1')
    keys = {s['key'] for s in bp.graph['stages']}
    by_key = {s['key']: s for s in bp.graph['stages']}
    assert 'package_zip' in keys
    assert 'editor_brief' in keys
    assert 'caption_bundle' in keys
    assert by_key['package_zip']['depends_on'] == ['caption_bundle']
    assert 'clip_preview_render' not in keys
    assert 'clip_distribute' not in keys
    assert 'clip_render' not in keys


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
    assert by_key['visual_anchors']['depends_on'] == ['visual_prompts']
    assert by_key['image_gen']['depends_on'] == ['visual_anchors']
    assert by_key['scene_breakdown']['config']['min_words'] == 8
    assert by_key['motion']['config']['max_hero_scenes'] == 6
    assert by_key['motion']['config']['i2v_enabled'] is True
    assert by_key['storyboard_gate']['depends_on'] == ['image_gen']
    assert by_key['storyboard_gate'].get('gate') is True
    assert by_key['tts']['depends_on'] == ['storyboard_gate']
    assert by_key['motion']['depends_on'] == ['storyboard_gate']
    assert by_key['final_gate']['depends_on'] == [
        'qc',
        'thumbnail',
        'metadata',
    ]
    assert by_key['final_gate'].get('gate') is True
    assert by_key['publish']['depends_on'] == ['final_gate']
    assert by_key['metadata']['depends_on'] == ['script', 'alignment']
    assert by_key['thumbnail']['depends_on'] == ['metadata']
