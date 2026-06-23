"""Controller error-path tests for ideation API."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr.endpoint import Endpoint

from server.apps.ideas.api.views import (
    IdeaCollectionController,
    IdeaDetailController,
    IdeaPromoteController,
    NicheIdeaGenerateController,
)
from server.apps.ideas.logic.value_objects import IdeaListPayload
from server.apps.ideas.models import TopicIdea


def test_collection_invalid_limit_defaults_to_twenty() -> None:
    """Non-integer limit query values fall back to 20."""
    controller = IdeaCollectionController()
    controller.request = MagicMock()
    controller.request.GET.get = lambda key, default=None: {
        'limit': 'bad',
    }.get(key, default)
    service = MagicMock()
    service.list_backlog.return_value = IdeaListPayload(
        items=[],
        next_cursor=None,
        total=0,
    )
    with patch.object(controller, 'resolve', return_value=service):
        controller.get()
    service.list_backlog.assert_called_once_with(
        status=None,
        channel_id=None,
        niche_id=None,
        cursor=None,
        limit=20,
    )


@pytest.mark.parametrize(
    'controller_cls',
    [
        IdeaDetailController,
        NicheIdeaGenerateController,
        IdeaPromoteController,
    ],
)
def test_handle_error_delegates_unknown_exceptions(
    controller_cls: type,
) -> None:
    """Unknown exceptions fall through to the base controller handler."""
    controller = controller_cls()
    endpoint = MagicMock(spec=Endpoint)
    fallback = HttpResponse(status=HTTPStatus.INTERNAL_SERVER_ERROR)
    with patch(
        'dmr.controller.Controller.handle_error',
        return_value=fallback,
    ) as mock_super:
        response = controller.handle_error(
            endpoint,
            MagicMock(spec=controller_cls),
            RuntimeError('unexpected'),
        )
    assert response is fallback
    mock_super.assert_called_once()


def test_detail_handle_error_maps_validation_error() -> None:
    """Detail maps ValidationError to 422."""
    controller = IdeaDetailController()
    controller.request = MagicMock()
    endpoint = MagicMock(spec=Endpoint)
    response = controller.handle_error(
        endpoint,
        MagicMock(spec=IdeaDetailController),
        ValidationError('bad patch'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_promote_handle_error_maps_missing_idea() -> None:
    """Promote maps DoesNotExist to a 404 error response."""
    controller = IdeaPromoteController()
    controller.request = MagicMock()
    endpoint = MagicMock(spec=Endpoint)
    response = controller.handle_error(
        endpoint,
        MagicMock(spec=IdeaPromoteController),
        TopicIdea.DoesNotExist(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_generate_handle_error_maps_validation_error() -> None:
    """Generate maps ValidationError to 422."""
    controller = NicheIdeaGenerateController()
    controller.request = MagicMock()
    endpoint = MagicMock(spec=Endpoint)
    response = controller.handle_error(
        endpoint,
        MagicMock(spec=NicheIdeaGenerateController),
        ValidationError('bad input'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_detail_handle_error_maps_missing_idea() -> None:
    """Detail maps DoesNotExist to a 404 error response."""
    controller = IdeaDetailController()
    controller.request = MagicMock()
    endpoint = MagicMock(spec=Endpoint)
    response = controller.handle_error(
        endpoint,
        MagicMock(spec=IdeaDetailController),
        TopicIdea.DoesNotExist(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
