"""Read-only query helpers for run cast."""

from server.apps.pipelines.logic.value_objects import (
    RunCastListPayload,
    RunCastPayload,
)
from server.apps.pipelines.models import RunCast


def _to_cast(row: RunCast) -> RunCastPayload:
    character = row.character
    return RunCastPayload(
        id=str(row.id),
        run_id=str(row.run_id),
        character_id=str(row.character_id),
        character_name=character.name,
        role=row.role,
        is_ephemeral=row.is_ephemeral,
        design_status=row.design_status,
        hero_ref_asset_id=(
            str(character.hero_ref_id) if character.hero_ref_id else None
        ),
    )


def list_run_cast(run_id: str) -> RunCastListPayload:
    """Return cast assignments for a run."""
    items = [
        _to_cast(row)
        for row in RunCast.objects.filter(run_id=run_id).select_related(  # type: ignore[misc]
            'character',
        )
    ]
    return RunCastListPayload(items=items, total=len(items))
