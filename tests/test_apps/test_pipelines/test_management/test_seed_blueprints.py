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
