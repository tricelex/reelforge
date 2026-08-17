"""Tests for pipeline blueprint CRUD API."""

import uuid
from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

_MIN_GRAPH = {
    'stages': [
        {'key': 'research', 'depends_on': [], 'queue': 'api'},
        {'key': 'outline', 'depends_on': ['research'], 'queue': 'api'},
    ],
}


@pytest.fixture
def blueprint(db: None) -> PipelineBlueprint:
    """Active longform blueprint with a small graph."""
    return PipelineBlueprint.objects.create(
        name='onboard_longform_v1',
        kind=PipelineKind.LONGFORM,
        graph=_MIN_GRAPH,
        is_active=True,
        version=1,
    )


@pytest.mark.django_db
def test_get_blueprint_detail_returns_graph(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': blueprint.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['id'] == str(blueprint.id)
    assert body['name'] == 'onboard_longform_v1'
    assert body['kind'] == PipelineKind.LONGFORM
    assert body['graph'] == _MIN_GRAPH
    assert body['version'] == 1
    assert body['is_active'] is True


@pytest.mark.django_db
def test_get_blueprint_detail_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_create_blueprint(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:pipelines_api:blueprint-collection'),
        data={
            'name': 'cloned_longform_v1',
            'kind': PipelineKind.LONGFORM,
            'graph': _MIN_GRAPH,
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['name'] == 'cloned_longform_v1'
    assert body['graph']['stages'][0]['key'] == 'research'
    assert PipelineBlueprint.objects.filter(id=body['id']).exists()


@pytest.mark.django_db
def test_create_blueprint_rejects_unknown_stage(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:pipelines_api:blueprint-collection'),
        data={
            'name': 'bad_graph',
            'kind': PipelineKind.LONGFORM,
            'graph': {
                'stages': [
                    {'key': 'not_a_real_stage', 'depends_on': []},
                ],
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not PipelineBlueprint.objects.filter(name='bad_graph').exists()


@pytest.mark.django_db
def test_create_blueprint_rejects_unknown_dependency(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:pipelines_api:blueprint-collection'),
        data={
            'name': 'bad_deps',
            'kind': PipelineKind.LONGFORM,
            'graph': {
                'stages': [
                    {
                        'key': 'outline',
                        'depends_on': ['missing_upstream'],
                    },
                ],
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_create_blueprint_rejects_duplicate_name(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:pipelines_api:blueprint-collection'),
        data={
            'name': blueprint.name,
            'kind': PipelineKind.LONGFORM,
            'graph': _MIN_GRAPH,
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_patch_blueprint_graph_bumps_version(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    new_graph = {
        'stages': [
            {'key': 'research', 'depends_on': [], 'queue': 'api'},
            {'key': 'script', 'depends_on': ['research'], 'queue': 'api'},
        ],
    }
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': blueprint.id},
        ),
        data={'graph': new_graph},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['version'] == 2
    assert body['graph'] == new_graph
    blueprint.refresh_from_db()
    assert blueprint.version == 2
    assert blueprint.graph == new_graph


@pytest.mark.django_db
def test_patch_blueprint_deactivate(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': blueprint.id},
        ),
        data={'is_active': False},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['is_active'] is False
    assert response.json()['version'] == 1


@pytest.mark.django_db
def test_create_blueprint_rejects_empty_name(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:pipelines_api:blueprint-collection'),
        data={
            'name': '   ',
            'kind': PipelineKind.LONGFORM,
            'graph': _MIN_GRAPH,
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_create_blueprint_rejects_invalid_kind(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:pipelines_api:blueprint-collection'),
        data={
            'name': 'kind_fail',
            'kind': 'NOT_A_KIND',
            'graph': _MIN_GRAPH,
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_patch_blueprint_rejects_empty_name(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': blueprint.id},
        ),
        data={'name': '  '},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_patch_blueprint_rejects_duplicate_name(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    other = PipelineBlueprint.objects.create(
        name='other_bp_v1',
        kind=PipelineKind.LONGFORM,
        graph=_MIN_GRAPH,
        is_active=True,
    )
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': other.id},
        ),
        data={'name': blueprint.name},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_patch_blueprint_same_graph_does_not_bump_version(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': blueprint.id},
        ),
        data={'graph': _MIN_GRAPH},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['version'] == 1


@pytest.mark.django_db
def test_patch_blueprint_kind(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': blueprint.id},
        ),
        data={'kind': PipelineKind.SHORTS},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['kind'] == PipelineKind.SHORTS


@pytest.mark.django_db
def test_get_blueprint_detail_non_dict_graph(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    row = PipelineBlueprint.objects.create(
        name='legacy_empty_graph',
        kind=PipelineKind.LONGFORM,
        graph=['not', 'an', 'object'],
        is_active=True,
    )
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:blueprint-detail',
            kwargs={'blueprint_id': row.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['graph'] == {}
