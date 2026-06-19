"""OpenAPI tag coverage for the unified ReelForge API schema."""

import json
from http import HTTPStatus
from typing import Any, Final

import pytest
from django.test import Client
from django.urls import reverse

from server.common.openapi_tags import ALL_TAGS

_OPENAPI_URL: Final = reverse('openapi_json')

# path -> HTTP method -> expected primary tag (last tag wins for grouping)
_TAGGED_OPERATIONS: Final = {
    '/api/auth/me/': {'get': 'Auth'},
    '/api/enums/': {'get': 'Enums'},
    '/api/dashboard/': {'get': 'Analytics'},
    '/api/ideas/': {'get': 'Ideas'},
    '/api/runs/': {'post': 'Pipeline Runs'},
    '/api/runs/{run_id}/storyboard/': {'get': 'Pipeline Review'},
    '/api/runs/{run_id}/cast/': {'get': 'Pipeline Cast'},
    '/api/blueprints/': {'get': 'Blueprints'},
    '/api/candidates/{candidate_id}/layout-config/': {'get': 'Clip Config'},
    '/api/candidates/{candidate_id}/posts/': {'get': 'Clip Posts'},
    '/api/campaigns/': {'get': 'Campaigns'},
    '/api/channels/': {'get': 'Channels'},
    '/api/characters/': {'get': 'Characters'},
    '/api/channels/{channel_id}/youtube/status/': {'get': 'YouTube'},
}


def _load_openapi_schema(client: Client) -> dict[str, Any]:
    response = client.get(_OPENAPI_URL)
    assert response.status_code == HTTPStatus.OK
    return json.loads(response.content)


def _operation_tags(
    schema: dict[str, Any],
    path: str,
    method: str,
) -> list[str]:
    path_item = schema['paths'][path]
    operation = path_item[method]
    tags = operation.get('tags')
    assert tags is not None, f'{method.upper()} {path} has no tags'
    return list(tags)


@pytest.mark.django_db
def test_openapi_root_tag_definitions(client: Client) -> None:
    """Root-level tag definitions include every known tag with descriptions."""
    schema = _load_openapi_schema(client)
    root_tags = {item['name']: item.get('description', '') for item in schema['tags']}
    assert set(root_tags) == set(ALL_TAGS)
    assert all(description for description in root_tags.values())


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('path', 'method', 'expected_tag'),
    [
        (path, method, tag)
        for path, methods in _TAGGED_OPERATIONS.items()
        for method, tag in methods.items()
    ],
)
def test_openapi_operation_has_expected_tag(
    client: Client,
    path: str,
    method: str,
    expected_tag: str,
) -> None:
    """Representative operations carry the expected OpenAPI tag."""
    schema = _load_openapi_schema(client)
    tags = _operation_tags(schema, path, method)
    assert expected_tag in tags


@pytest.mark.django_db
def test_openapi_api_paths_are_tagged(client: Client) -> None:
    """Every /api/ operation in the schema has at least one tag."""
    schema = _load_openapi_schema(client)
    untagged: list[str] = []
    for path, path_item in schema['paths'].items():
        if not path.startswith('/api/'):
            continue
        for method, operation in path_item.items():
            if method == 'parameters':
                continue
            tags = operation.get('tags')
            if not tags:
                untagged.append(f'{method.upper()} {path}')
    assert untagged == []
