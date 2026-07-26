"""Structural validation for every seeded blueprint graph."""

import pytest
from django.core.management import call_command

from server.apps.pipelines.models import PipelineBlueprint
from server.apps.pipelines.stages.base import STAGE_REGISTRY


def _graphs() -> list[tuple[str, list[dict[str, object]]]]:
    return [
        (bp.name, bp.graph.get('stages', []))
        for bp in PipelineBlueprint.objects.all()
    ]


@pytest.mark.django_db
def test_every_stage_key_is_registered() -> None:
    """A blueprint naming an unregistered stage would deadlock a run."""
    call_command('seed_blueprints')
    for name, stages in _graphs():
        for node in stages:
            assert node['key'] in STAGE_REGISTRY, (
                f'{name}: unregistered stage {node["key"]}'
            )


@pytest.mark.django_db
def test_every_dependency_resolves() -> None:
    """depends_on must reference a node present in the same graph."""
    call_command('seed_blueprints')
    for name, stages in _graphs():
        keys = {node['key'] for node in stages}
        for node in stages:
            for dep in node.get('depends_on', []):
                assert dep in keys, f'{name}: {node["key"]} needs missing {dep}'


@pytest.mark.django_db
def test_no_graph_has_a_cycle() -> None:
    """A dependency cycle would never become runnable."""
    call_command('seed_blueprints')
    for name, stages in _graphs():
        deps = {n['key']: set(n.get('depends_on', [])) for n in stages}
        resolved: set[str] = set()
        progressed = True
        while progressed:
            progressed = False
            for key, required in deps.items():
                if key not in resolved and required <= resolved:
                    resolved.add(key)
                    progressed = True
        assert resolved == set(deps), (
            f'{name}: cycle among {set(deps) - resolved}'
        )


@pytest.mark.django_db
def test_documentary_blueprint_is_seeded() -> None:
    """The documentary blueprint exists with the right profile."""
    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_documentary_v1')
    assert bp.graph['profile'] == 'documentary_footage'
    assert bp.is_active is True


@pytest.mark.django_db
def test_documentary_graph_has_no_character_stages() -> None:
    """There is no AI cast in a documentary pipeline."""
    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_documentary_v1')
    keys = {n['key'] for n in bp.graph['stages']}
    assert 'cast_proposal' not in keys
    assert 'character_gate' not in keys
    assert {'footage_queries', 'footage_search', 'footage_prep'} <= keys


@pytest.mark.django_db
def test_longform_v1_graph_declares_no_profile() -> None:
    """The AI blueprint is untouched and relies on the default profile."""
    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_v1')
    assert 'profile' not in bp.graph
