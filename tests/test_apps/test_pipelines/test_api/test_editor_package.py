"""API tests for editor-handoff package status and rebuild endpoints."""

import uuid
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import Asset, AssetKind
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.services.editor_package import (
    EditorPackageService,
)
from server.common.storage import PresignUrlHelper

_REBUILD_TARGET = (
    'server.apps.pipelines.services.editor_package.rerun_stage_impl'
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create a longform channel shared by editor/non-editor runs."""
    return Channel.objects.create(
        name='Editor Package Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=[],
        default_budget_usd='30.00',
    )


@pytest.fixture
def editor_blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create the editor-handoff blueprint graph (name-matched)."""
    return PipelineBlueprint.objects.create(
        name='longform_editor_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'handoff': 'editor_package',
            'stages': [
                {'key': 'editor_brief', 'depends_on': []},
                {
                    'key': 'timeline_export',
                    'depends_on': ['editor_brief'],
                },
                {
                    'key': 'caption_bundle',
                    'depends_on': ['timeline_export'],
                },
                {'key': 'package_zip', 'depends_on': ['caption_bundle']},
            ],
        },
    )


@pytest.fixture
def non_editor_blueprint(
    db,  # type: ignore[no-untyped-def]
) -> PipelineBlueprint:
    """Create a plain longform blueprint with no editor-handoff tail."""
    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'scene_breakdown', 'depends_on': []},
                {'key': 'assembly', 'depends_on': ['scene_breakdown']},
                {'key': 'final_gate', 'depends_on': ['assembly']},
                {'key': 'publish', 'depends_on': ['final_gate']},
            ],
        },
    )


@pytest.fixture
def editor_run(
    channel: Channel,
    editor_blueprint: PipelineBlueprint,
) -> PipelineRun:
    """Create an editor-handoff run."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=editor_blueprint,
        blueprint_snapshot=editor_blueprint.graph,
        topic='Editor package topic',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='4.50',
    )


@pytest.fixture
def non_editor_run(
    channel: Channel,
    non_editor_blueprint: PipelineBlueprint,
) -> PipelineRun:
    """Create a non-editor-handoff run."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=non_editor_blueprint,
        blueprint_snapshot=non_editor_blueprint.graph,
        topic='Non editor topic',
        status=RunStatus.AWAITING_REVIEW,
    )


@pytest.mark.django_db
def test_get_package_pending_for_editor_run_without_package_zip(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET package returns pending when package_zip has never run."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-package',
            kwargs={'run_id': editor_run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['status'] == 'pending'
    assert body['download_url'] is None


@pytest.mark.django_db
def test_get_package_unavailable_for_non_editor_run(
    dmr_client: DMRClient,
    non_editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET package returns unavailable for a non-editor-handoff run."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-package',
            kwargs={'run_id': non_editor_run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['status'] == 'unavailable'


@pytest.mark.django_db
def test_get_package_building_while_package_zip_running(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET package returns building while package_zip is in flight."""
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-package',
            kwargs={'run_id': editor_run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['status'] == 'building'


@pytest.mark.django_db
def test_get_package_failed_when_package_zip_failed(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET package returns failed when package_zip attempt failed."""
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.FAILED,
        attempt=0,
        error={'type': 'FatalProviderError', 'message': 'boom'},
    )

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-package',
            kwargs={'run_id': editor_run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['status'] == 'failed'


@pytest.mark.django_db
def test_get_package_ready_with_download_url(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET package returns ready with a presigned download URL."""
    asset = Asset.objects.create(
        kind=AssetKind.PACKAGE,
        file=ContentFile(b'PK\x03\x04', name='pkg.zip'),
        mime='application/zip',
        checksum='pkg123',
        run=editor_run,
    )
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'package_asset_id': str(asset.id),
            'size_bytes': 4096,
            'entry_count': 12,
            'root_name': 'run_abcd1234_longform_editor_package',
        },
    )

    with patch(
        'server.common.storage.PresignUrlHelper.presign_get',
        return_value='https://storage.example/pkg.zip',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-package',
                kwargs={'run_id': editor_run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['status'] == 'ready'
    assert body['download_url'] == 'https://storage.example/pkg.zip'
    assert body['package_asset_id'] == str(asset.id)
    assert body['size_bytes'] == 4096
    assert body['entry_count'] == 12
    assert body['root_name'] == 'run_abcd1234_longform_editor_package'
    assert body['built_at'] is not None


@pytest.mark.django_db
def test_get_package_missing_run_returns_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET package for an unknown run id returns 404."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-package',
            kwargs={'run_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_rebuild_package_rejects_non_editor_blueprint(
    dmr_client: DMRClient,
    non_editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST rebuild-package returns 409 for a non-editor-handoff run."""
    with patch(_REBUILD_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-rebuild-package',
                kwargs={'run_id': non_editor_run.id},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.CONFLICT
    mock_rerun.assert_not_called()


@pytest.mark.django_db
def test_rebuild_package_rejects_cancelled_run(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST rebuild-package returns 409 for a cancelled run."""
    editor_run.status = RunStatus.CANCELLED
    editor_run.save(update_fields=['status'])

    with patch(_REBUILD_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-rebuild-package',
                kwargs={'run_id': editor_run.id},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.CONFLICT
    mock_rerun.assert_not_called()


@pytest.mark.django_db
def test_rebuild_package_rejects_running_before_handoff_reached(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST rebuild-package returns 409 when the run hasn't reached package_zip."""
    editor_run.status = RunStatus.RUNNING
    editor_run.save(update_fields=['status'])

    with patch(_REBUILD_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-rebuild-package',
                kwargs={'run_id': editor_run.id},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.CONFLICT
    mock_rerun.assert_not_called()


@pytest.mark.django_db
def test_rebuild_package_queues_editor_brief_for_editor_run(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST rebuild-package requeues editor_brief for an editor-handoff run."""
    with patch(_REBUILD_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-rebuild-package',
                kwargs={'run_id': editor_run.id},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['status'] == 'queued'
    assert body['stage_key'] == 'editor_brief'
    mock_rerun.assert_called_once_with(str(editor_run.id), 'editor_brief')


@pytest.mark.django_db
def test_rebuild_package_allows_running_when_package_zip_exists(
    dmr_client: DMRClient,
    editor_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Rebuild is allowed for a RUNNING run once package_zip has attempted."""
    editor_run.status = RunStatus.RUNNING
    editor_run.save(update_fields=['status'])
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'package_asset_id': str(uuid.uuid4())},
    )

    with patch(_REBUILD_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-rebuild-package',
                kwargs={'run_id': editor_run.id},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    mock_rerun.assert_called_once_with(str(editor_run.id), 'editor_brief')


@pytest.mark.django_db
def test_rebuild_package_missing_run_returns_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST rebuild-package for an unknown run id returns 404."""
    with patch(_REBUILD_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-rebuild-package',
                kwargs={'run_id': uuid.uuid4()},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.NOT_FOUND
    mock_rerun.assert_not_called()


def _service() -> EditorPackageService:
    return EditorPackageService(presign=MagicMock(spec=PresignUrlHelper))


@pytest.mark.django_db
def test_get_package_pending_when_execution_neither_building_nor_terminal(
    editor_run: PipelineRun,
) -> None:
    """A SKIPPED package_zip attempt falls back to pending for editor runs."""
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.SKIPPED,
        attempt=0,
    )

    result = _service().get_package(str(editor_run.id))

    assert result.status == 'pending'


@pytest.mark.django_db
def test_ready_payload_missing_package_asset_id_is_failed(
    editor_run: PipelineRun,
) -> None:
    """A succeeded package_zip attempt with no package_asset_id is failed."""
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={},
    )

    result = _service().get_package(str(editor_run.id))

    assert result.status == 'failed'


@pytest.mark.django_db
def test_ready_payload_missing_asset_row_is_failed(
    editor_run: PipelineRun,
) -> None:
    """A package_asset_id pointing at a deleted Asset row is failed."""
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'package_asset_id': str(uuid.uuid4())},
    )

    result = _service().get_package(str(editor_run.id))

    assert result.status == 'failed'


@pytest.mark.django_db
def test_ready_payload_missing_file_name_is_failed(
    editor_run: PipelineRun,
) -> None:
    """An Asset with no stored file name is failed."""
    asset = Asset.objects.create(
        kind=AssetKind.PACKAGE,
        file='',
        mime='application/zip',
        checksum='no-file',
        run=editor_run,
    )
    StageExecution.objects.create(
        run=editor_run,
        stage_key='package_zip',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'package_asset_id': str(asset.id)},
    )

    result = _service().get_package(str(editor_run.id))

    assert result.status == 'failed'
