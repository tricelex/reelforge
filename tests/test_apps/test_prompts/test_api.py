"""Tests for prompts DMR API."""

from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.prompts.models import PromptScope


@pytest.mark.django_db
def test_create_and_list_prompt_templates(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    create_response = dmr_client.post(
        reverse('api:prompts_api:prompt-template-collection'),
        data={
            'name': 'Scene Breakdown',
            'key': 'scene_breakdown',
            'scope': PromptScope.GLOBAL,
        },
        headers=auth_headers,
    )
    assert create_response.status_code == HTTPStatus.CREATED
    template_id = create_response.json()['id']

    list_response = dmr_client.get(
        reverse('api:prompts_api:prompt-template-collection'),
        headers=auth_headers,
    )
    assert list_response.status_code == HTTPStatus.OK
    assert list_response.json()['total'] >= 1

    version_response = dmr_client.post(
        reverse(
            'api:prompts_api:prompt-version-collection',
            kwargs={'template_id': template_id},
        ),
        data={
            'system_prompt': 'You are helpful.',
            'user_prompt': 'Break down the script.',
        },
        headers=auth_headers,
    )
    assert version_response.status_code == HTTPStatus.CREATED
    assert version_response.json()['version'] == 1

    activate_response = dmr_client.post(
        reverse(
            'api:prompts_api:prompt-version-activate',
            kwargs={'template_id': template_id, 'version': 1},
        ),
        headers=auth_headers,
    )
    assert activate_response.status_code == HTTPStatus.OK
    assert activate_response.json()['is_active'] is True


@pytest.mark.django_db
def test_story_format_crud(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    create_response = dmr_client.post(
        reverse('api:prompts_api:story-format-collection'),
        data={
            'key': 'true_crime_case',
            'name': 'True Crime Case',
            'fiction': False,
            'beats': [
                {
                    'key': 'cold_open',
                    'pct': 0.05,
                    'purpose': 'hook',
                    'device': 'open_loop',
                },
            ],
        },
        headers=auth_headers,
    )
    assert create_response.status_code == HTTPStatus.CREATED
    format_id = create_response.json()['id']

    get_response = dmr_client.get(
        reverse(
            'api:prompts_api:story-format-detail',
            kwargs={'format_id': format_id},
        ),
        headers=auth_headers,
    )
    assert get_response.status_code == HTTPStatus.OK
    assert get_response.json()['key'] == 'true_crime_case'

    patch_response = dmr_client.patch(
        reverse(
            'api:prompts_api:story-format-detail',
            kwargs={'format_id': format_id},
        ),
        data={'name': 'True Crime Updated'},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.OK
    assert patch_response.json()['name'] == 'True Crime Updated'


@pytest.mark.django_db
def test_prompt_template_404_get_and_patch(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Missing prompt template returns 404 on GET and PATCH."""
    import uuid

    template_id = uuid.uuid4()
    detail_url = reverse(
        'api:prompts_api:prompt-template-detail',
        kwargs={'template_id': template_id},
    )
    get_response = dmr_client.get(detail_url, headers=auth_headers)
    assert get_response.status_code == HTTPStatus.NOT_FOUND

    patch_response = dmr_client.patch(
        detail_url,
        data={'name': 'Missing'},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_prompt_template_version_list_and_activate_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Version list works; activating missing version returns 404."""
    create_response = dmr_client.post(
        reverse('api:prompts_api:prompt-template-collection'),
        data={
            'name': 'Versioned',
            'key': 'versioned_prompt',
            'scope': PromptScope.GLOBAL,
        },
        headers=auth_headers,
    )
    template_id = create_response.json()['id']

    list_response = dmr_client.get(
        reverse(
            'api:prompts_api:prompt-version-collection',
            kwargs={'template_id': template_id},
        ),
        headers=auth_headers,
    )
    assert list_response.status_code == HTTPStatus.OK
    assert list_response.json()['total'] == 0

    activate_response = dmr_client.post(
        reverse(
            'api:prompts_api:prompt-version-activate',
            kwargs={'template_id': template_id, 'version': 99},
        ),
        headers=auth_headers,
    )
    assert activate_response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_prompt_template_patch_name(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """PATCH updates prompt template name."""
    create_response = dmr_client.post(
        reverse('api:prompts_api:prompt-template-collection'),
        data={
            'name': 'Original Name',
            'key': 'rename_prompt',
            'scope': PromptScope.GLOBAL,
        },
        headers=auth_headers,
    )
    template_id = create_response.json()['id']

    patch_response = dmr_client.patch(
        reverse(
            'api:prompts_api:prompt-template-detail',
            kwargs={'template_id': template_id},
        ),
        data={'name': 'Renamed Template'},
        headers=auth_headers,
    )

    assert patch_response.status_code == HTTPStatus.OK
    assert patch_response.json()['name'] == 'Renamed Template'


@pytest.mark.django_db
def test_story_formats_active_filter_and_format_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Story formats support ?active=true; missing format PATCH returns 404."""
    from server.apps.prompts.models import StoryFormat

    StoryFormat.objects.create(
        key='inactive_format',
        name='Inactive',
        beats=[],
        is_active=False,
    )
    active = StoryFormat.objects.create(
        key='active_format',
        name='Active',
        beats=[],
        is_active=True,
    )

    list_response = dmr_client.get(
        f'{reverse("api:prompts_api:story-format-collection")}?active=true',
        headers=auth_headers,
    )
    assert list_response.status_code == HTTPStatus.OK
    ids = {item['id'] for item in list_response.json()['items']}
    assert str(active.id) in ids

    import uuid

    patch_response = dmr_client.patch(
        reverse(
            'api:prompts_api:story-format-detail',
            kwargs={'format_id': uuid.uuid4()},
        ),
        data={'name': 'Missing'},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.NOT_FOUND
