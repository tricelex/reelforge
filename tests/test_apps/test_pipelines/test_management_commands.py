"""Tests for the pipelines management commands."""

import pytest
from django.core.management import call_command

from server.apps.pipelines.models import PipelineBlueprint, PipelineKind


@pytest.mark.django_db
def test_seed_blueprints_creates_longform_v1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """seed_blueprints creates the longform_v1 blueprint idempotently."""
    assert not PipelineBlueprint.objects.filter(name='longform_v1').exists()

    call_command('seed_blueprints')

    bp = PipelineBlueprint.objects.get(name='longform_v1')
    assert bp.kind == PipelineKind.LONGFORM
    assert bp.is_active is True
    assert 'stages' in bp.graph
    assert len(bp.graph['stages']) > 0

    captured = capsys.readouterr()
    assert 'Created' in captured.out


@pytest.mark.django_db
def test_seed_blueprints_is_idempotent() -> None:
    """Calling seed_blueprints twice updates, not duplicates, the blueprint."""
    call_command('seed_blueprints')
    call_command('seed_blueprints')

    assert PipelineBlueprint.objects.filter(name='longform_v1').count() == 1
