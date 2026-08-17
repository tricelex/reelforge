"""Shared validation for pipeline blueprint names and graphs."""

from itertools import starmap
from typing import Any, Final
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.pipelines.logic.constants import BLUEPRINT_BY_KIND
from server.apps.pipelines.models import PipelineBlueprint, PipelineKind
from server.apps.pipelines.stages.base import STAGE_REGISTRY

_ALLOWED_QUEUES: Final = frozenset({'api', 'render', 'gpu'})


def validate_blueprint_graph(graph: object) -> dict[str, Any]:
    """Return a copy of *graph* after validating the stages DAG."""
    if not isinstance(graph, dict):
        msg = 'graph must be a JSON object'
        raise ValidationError(msg)
    stages = graph.get('stages')
    if not isinstance(stages, list) or not stages:
        msg = 'graph.stages must be a non-empty list'
        raise ValidationError(msg)
    keys = list(starmap(_validated_stage_key, enumerate(stages)))
    _validate_dependencies(stages, set(keys))
    return dict(graph)


def _validated_stage_key(index: int, node: object) -> str:
    """Return a unique registered stage key from one graph node."""
    if not isinstance(node, dict):
        msg = f'graph.stages[{index}] must be an object'
        raise ValidationError(msg)
    key = node.get('key')
    if not isinstance(key, str) or not key:
        msg = f'graph.stages[{index}].key is required'
        raise ValidationError(msg)
    if key not in STAGE_REGISTRY:
        msg = f'unknown stage key: {key}'
        raise ValidationError(msg)
    _validate_stage_node(key, node)
    return key


def _validate_dependencies(stages: list[object], key_set: set[str]) -> None:
    """Raise when depends_on is not a list of keys in this graph."""
    seen: set[str] = set()
    for node in stages:
        if isinstance(node, dict):
            _validate_node_edges(node, seen, key_set)


def _validate_node_edges(
    node: dict[str, Any],
    seen: set[str],
    key_set: set[str],
) -> None:
    """Validate uniqueness and depends_on for one stage node."""
    key = str(node.get('key', ''))
    if key in seen:
        msg = f'duplicate stage key: {key}'
        raise ValidationError(msg)
    seen.add(key)
    depends = node.get('depends_on', [])
    if not isinstance(depends, list):
        msg = f'stage {key}: depends_on must be a list'
        raise ValidationError(msg)
    _validate_dep_list(key, depends, key_set)


def _validate_dep_list(
    key: str,
    depends: list[object],
    key_set: set[str],
) -> None:
    """Raise when a dependency is missing from this graph."""
    for dep in depends:
        if not isinstance(dep, str) or dep not in key_set:
            msg = f'stage {key}: unknown dependency {dep!r}'
            raise ValidationError(msg)


def _validate_stage_node(key: str, node: dict[str, Any]) -> None:
    queue = node.get('queue')
    if queue is not None and queue not in _ALLOWED_QUEUES:
        msg = f'stage {key}: queue must be one of {sorted(_ALLOWED_QUEUES)}'
        raise ValidationError(msg)
    if 'gate' in node and not isinstance(node['gate'], bool):
        msg = f'stage {key}: gate must be a boolean'
        raise ValidationError(msg)
    if 'config' in node and not isinstance(node['config'], dict):
        msg = f'stage {key}: config must be an object'
        raise ValidationError(msg)
    fan_out = node.get('fan_out')
    if fan_out is not None and not isinstance(fan_out, str):
        msg = f'stage {key}: fan_out must be a string'
        raise ValidationError(msg)


def validate_blueprint_kind(kind: str) -> None:
    """Raise ValidationError when *kind* is not a PipelineKind value."""
    if kind not in PipelineKind.values:
        msg = f'invalid blueprint kind: {kind}'
        raise ValidationError(msg)


def ensure_unique_blueprint_name(
    name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    """Raise ValidationError when another blueprint already uses *name*."""
    qs = PipelineBlueprint.objects.filter(name=name)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        msg = f'Blueprint name already exists: {name}'
        raise ValidationError(msg)


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
