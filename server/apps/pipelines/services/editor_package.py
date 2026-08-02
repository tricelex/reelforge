"""Business logic for editor-handoff package status and rebuild."""

import asyncio
import uuid
from typing import final

import attrs
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.pipelines.logic.editor_handoff import (
    HANDOFF_TAIL_START,
    is_editor_handoff_blueprint,
)
from server.apps.pipelines.logic.value_objects import (
    PackagePayload,
    RebuildPackageResultPayload,
)
from server.apps.pipelines.models import (
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.services.orchestrator import rerun_stage_impl
from server.apps.pipelines.storyboard_selectors import _latest_parent_execution
from server.common.storage import PresignUrlHelper

_BUILDING_STATUSES = frozenset({
    StageStatus.PENDING,
    StageStatus.QUEUED,
    StageStatus.RUNNING,
})


def _load_run(run_id: str) -> PipelineRun:
    """Load a PipelineRun with its blueprint, or raise DoesNotExist."""
    assert run_id, 'run_id is required'  # noqa: S101
    return PipelineRun.objects.select_related('blueprint').get(
        id=uuid.UUID(run_id),
    )


def _pending_or_unavailable(*, is_editor: bool) -> PackagePayload:
    """Return the payload for a run with no package_zip attempt yet."""
    return PackagePayload(status='pending' if is_editor else 'unavailable')


@final
@attrs.define(slots=True, frozen=True)
class EditorPackageService:
    """Read editor-handoff package build status and trigger rebuilds."""

    _presign: PresignUrlHelper

    def get_package(self, run_id: str) -> PackagePayload:
        """Return the package_zip build status/download URL for a run."""
        assert run_id, 'run_id is required'  # noqa: S101
        run = _load_run(run_id)
        is_editor = is_editor_handoff_blueprint(
            run.blueprint.name,
            snapshot=run.blueprint_snapshot,
        )

        execution = _latest_parent_execution(run_id, 'package_zip')
        if execution is None:
            return _pending_or_unavailable(is_editor=is_editor)
        if execution.status in _BUILDING_STATUSES:
            return PackagePayload(status='building')
        if execution.status == StageStatus.FAILED:
            return PackagePayload(status='failed')
        if execution.status != StageStatus.SUCCEEDED:
            return _pending_or_unavailable(is_editor=is_editor)

        return self._ready_payload(execution)

    def _ready_payload(self, execution: StageExecution) -> PackagePayload:
        """Build the 'ready' payload from a succeeded package_zip execution."""
        from server.apps.assets.models import Asset  # noqa: PLC0415

        output = execution.output
        asset_id = output.get('package_asset_id')
        if not asset_id:
            return PackagePayload(status='failed')

        try:
            asset = Asset.objects.get(id=asset_id)
        except ObjectDoesNotExist:
            return PackagePayload(status='failed')

        file_name = getattr(asset.file, 'name', None)
        if not file_name or not isinstance(file_name, str):
            return PackagePayload(status='failed')
        download_url = self._presign.presign_get(file_name)
        size_raw = output.get('size_bytes')
        entry_raw = output.get('entry_count')
        return PackagePayload(
            status='ready',
            download_url=download_url,
            package_asset_id=str(asset_id),
            built_at=execution.updated_at.isoformat(),
            size_bytes=int(size_raw) if size_raw is not None else None,
            entry_count=int(entry_raw) if entry_raw is not None else None,
            root_name=str(output['root_name'])
            if output.get('root_name')
            else None,
        )

    def rebuild_package(self, run_id: str) -> RebuildPackageResultPayload:
        """Requeue the editor-handoff tail (editor_brief onward)."""
        assert run_id, 'run_id is required'  # noqa: S101
        run = _load_run(run_id)
        if not is_editor_handoff_blueprint(
            run.blueprint.name,
            snapshot=run.blueprint_snapshot,
        ):
            msg = 'Run does not use an editor-handoff blueprint'
            raise ValidationError(msg)
        if run.status == RunStatus.CANCELLED:
            msg = 'Cannot rebuild package for a cancelled run'
            raise ValidationError(msg)

        package_execution = _latest_parent_execution(run_id, 'package_zip')
        if package_execution is None and run.status == RunStatus.RUNNING:
            msg = 'Run has not yet reached the editor-handoff stage'
            raise ValidationError(msg)

        asyncio.run(rerun_stage_impl(run_id, HANDOFF_TAIL_START))
        result = RebuildPackageResultPayload(
            status='queued',
            stage_key=HANDOFF_TAIL_START,
        )
        assert result.stage_key == HANDOFF_TAIL_START, (  # noqa: S101
            'stage_key must match the handoff tail start'
        )
        return result
