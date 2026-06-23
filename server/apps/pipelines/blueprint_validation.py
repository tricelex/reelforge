"""Shared validation for pipeline blueprint names."""

from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.pipelines.logic.constants import BLUEPRINT_BY_KIND
from server.apps.pipelines.models import PipelineBlueprint


def validate_active_blueprint_name(name: str) -> None:
    """Raise ValidationError when the blueprint name is missing or inactive."""
    if not name:
        msg = 'Blueprint name cannot be empty'
        raise ValidationError(msg)
    try:
        PipelineBlueprint.objects.get(name=name, is_active=True)
    except ObjectDoesNotExist as exc:
        msg = f'Blueprint not found: {name}'
        raise ValidationError(msg) from exc


def resolve_blueprint_name(
    *,
    channel_kind: str,
    channel_default: str | None,
    run_override: str | None,
) -> str:
    """Resolve the blueprint name for a new run."""
    default_name = channel_default or None
    blueprint_name = (
        run_override or default_name or BLUEPRINT_BY_KIND.get(channel_kind)
    )
    if blueprint_name is None:
        msg = f'No blueprint mapping for channel kind {channel_kind}'
        raise ValidationError(msg)
    validate_active_blueprint_name(blueprint_name)
    return blueprint_name
