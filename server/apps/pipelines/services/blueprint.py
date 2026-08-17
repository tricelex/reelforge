"""Business logic for pipeline blueprint CRUD."""

import uuid
from typing import final

import attrs
from django.core.exceptions import ValidationError

from server.apps.pipelines.blueprint_validation import (
    ensure_unique_blueprint_name,
    validate_blueprint_graph,
    validate_blueprint_kind,
)
from server.apps.pipelines.logic.value_objects import (
    BlueprintCreatePayload,
    BlueprintDetailPayload,
    BlueprintPatchPayload,
)
from server.apps.pipelines.models import PipelineBlueprint
from server.apps.pipelines.run_asset_selectors import get_blueprint_detail


@final
@attrs.define(slots=True, frozen=True)
class BlueprintService:
    """Create and update pipeline blueprints."""

    def create(
        self,
        payload: BlueprintCreatePayload,
    ) -> BlueprintDetailPayload:
        """Create a blueprint after validating name, kind, and graph."""
        name = payload.name.strip()
        if not name:
            msg = 'Blueprint name cannot be empty'
            raise ValidationError(msg)
        validate_blueprint_kind(payload.kind)
        ensure_unique_blueprint_name(name)
        graph = validate_blueprint_graph(payload.graph)
        row = PipelineBlueprint.objects.create(
            name=name,
            kind=payload.kind,
            graph=graph,
            is_active=payload.is_active,
            version=1,
        )
        return get_blueprint_detail(str(row.id))

    def patch(
        self,
        blueprint_id: str,
        payload: BlueprintPatchPayload,
    ) -> BlueprintDetailPayload:
        """Update a blueprint; bump version when the graph changes."""
        row = PipelineBlueprint.objects.get(id=uuid.UUID(blueprint_id))
        update_fields: list[str] = []
        _apply_name_patch(row, payload, update_fields)
        if payload.kind is not None:
            validate_blueprint_kind(payload.kind)
            row.kind = payload.kind
            update_fields.append('kind')
        if payload.is_active is not None:
            row.is_active = payload.is_active
            update_fields.append('is_active')
        _apply_graph_patch(row, payload, update_fields)
        if update_fields:
            row.save(update_fields=update_fields)
        return get_blueprint_detail(str(row.id))


def _apply_name_patch(
    row: PipelineBlueprint,
    payload: BlueprintPatchPayload,
    update_fields: list[str],
) -> None:
    """Apply a non-empty unique name when the patch includes one."""
    if payload.name is None:
        return
    name = payload.name.strip()
    if not name:
        msg = 'Blueprint name cannot be empty'
        raise ValidationError(msg)
    ensure_unique_blueprint_name(name, exclude_id=row.id)
    row.name = name
    update_fields.append('name')


def _apply_graph_patch(
    row: PipelineBlueprint,
    payload: BlueprintPatchPayload,
    update_fields: list[str],
) -> None:
    """Apply a validated graph and bump version when it actually changes."""
    if payload.graph is None:
        return
    graph = validate_blueprint_graph(payload.graph)
    if graph == row.graph:
        return
    row.graph = graph
    row.version = int(row.version) + 1
    update_fields.extend(['graph', 'version'])
