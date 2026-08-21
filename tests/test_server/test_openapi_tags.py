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
    '/api/channel-research/': {'get': 'Channel Research'},
    '/api/channel-research/validate-spec/': {'post': 'Channel Research'},
    '/api/channel-research/import/': {'post': 'Channel Research'},
    '/api/runs/': {'post': 'Pipeline Runs'},
    '/api/runs/{run_id}/events/': {'get': 'Pipeline Runs'},
    '/api/runs/{run_id}/storyboard/': {'get': 'Pipeline Review'},
    '/api/runs/{run_id}/cast/': {'get': 'Pipeline Cast'},
    '/api/blueprints/': {'get': 'Blueprints'},
    '/api/candidates/{candidate_id}/layout-config/': {'get': 'Clip Config'},
    '/api/candidates/{candidate_id}/layout-config/smart-crop/': {
        'post': 'Clip Config',
    },
    '/api/candidates/{candidate_id}/source-frame/': {'get': 'Clip Config'},
    '/api/candidates/{candidate_id}/posts/': {'get': 'Clip Posts'},
    '/api/campaigns/': {'get': 'Campaigns'},
    '/api/clip-sources/': {'get': 'Clip Sources'},
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


def _find_untagged_operations(schema: dict[str, Any]) -> list[str]:
    """Return untagged /api/ operations for schema validation tests."""
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
    return untagged


@pytest.mark.django_db
def test_openapi_root_tag_definitions(client: Client) -> None:
    """Root-level tag definitions include every known tag with descriptions."""
    schema = _load_openapi_schema(client)
    root_tags = {
        item['name']: item.get('description', '') for item in schema['tags']
    }
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
def test_openapi_layout_config_has_render_mode_enum(client: Client) -> None:
    """Layout config schema exposes render_mode enum values."""
    schema = _load_openapi_schema(client)
    components = schema.get('components', {}).get('schemas', {})
    layout = components.get('ClipLayoutConfigPayload', {})
    props = layout.get('properties', {})
    render_mode = props.get('render_mode', {})
    enum_values = set(render_mode.get('enum', []))
    assert 'SMART_CROP' in enum_values
    assert 'SPATIAL_STACK' in enum_values
    assert 'CENTER_CROP' in enum_values


@pytest.mark.django_db
def test_openapi_source_frame_has_time_sec_query_param(client: Client) -> None:
    """Source frame endpoint documents time_sec query parameter."""
    schema = _load_openapi_schema(client)
    operation = schema['paths']['/api/candidates/{candidate_id}/source-frame/'][
        'get'
    ]
    param_names = {
        p['name']
        for p in operation.get('parameters', [])
        if p.get('in') == 'query'
    }
    assert 'time_sec' in param_names


@pytest.mark.django_db
def test_openapi_channel_research_list_has_query_params(client: Client) -> None:
    """List jobs GET documents status, cursor, and limit query params."""
    schema = _load_openapi_schema(client)
    operation = schema['paths']['/api/channel-research/']['get']
    param_names = {
        p['name']
        for p in operation.get('parameters', [])
        if p.get('in') == 'query'
    }
    assert {'status', 'cursor', 'limit'} <= param_names


@pytest.mark.django_db
def test_openapi_channel_spec_payload_is_nested(client: Client) -> None:
    """ChannelSpecPayload is a named schema with the onboarding fields."""
    schema = _load_openapi_schema(client)
    components = schema.get('components', {}).get('schemas', {})
    spec = components.get('ChannelSpecPayload', {})
    props = spec.get('properties', {})
    expected = {
        'channel',
        'niche',
        'story_format',
        'prompt_templates',
        'branding',
        'assembly_style',
        'footage_sourcing',
        'character',
        'seed_ideas',
        'post_import_notes',
    }
    assert expected <= set(props)
    report = components.get('ResearchReportPayload', {})
    report_props = report.get('properties', {})
    assert 'visual_medium' in report_props
    medium = report_props['visual_medium']
    enum_values = set(medium.get('enum', []))
    assert '2d_animation' in enum_values
    assert 'photoreal' in enum_values
    job = components.get('ChannelResearchJobPayload', {})
    job_props = job.get('properties', {})
    spec_ref = str(job_props.get('channel_spec', {}))
    assert 'ChannelSpecPayload' in spec_ref or 'null' in spec_ref.lower()
    assert '/api/channel-research/validate-spec/' in schema['paths']


@pytest.mark.django_db
def test_openapi_build_api_schema() -> None:
    """build_api_schema accepts optional context."""
    from dmr.openapi import OpenAPIContext, default_config

    from server.openapi.routers import build_api_schema

    schema = build_api_schema(context=OpenAPIContext(config=default_config()))
    assert '/api/clip-sources/' in schema.paths


@pytest.mark.django_db
def test_openapi_api_paths_are_tagged(client: Client) -> None:
    """Every /api/ operation in the schema has at least one tag."""
    schema = _load_openapi_schema(client)
    assert _find_untagged_operations(schema) == []


def test_find_untagged_operations_skips_non_api_and_parameters() -> None:
    """Untagged scan ignores non-API paths and path-level parameters."""
    schema = {
        'paths': {
            '/health/': {'get': {'tags': ['Health']}},
            '/api/demo/': {
                'parameters': [{'name': 'x', 'in': 'query'}],
                'get': {'tags': ['Demo']},
                'post': {},
            },
        },
    }
    assert _find_untagged_operations(schema) == ['POST /api/demo/']
