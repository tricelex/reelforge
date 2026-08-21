"""Controller error-path tests for channel research API."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr.endpoint import Endpoint

from server.apps.channel_research.api.views import (
    ChannelResearchCollectionController,
    ChannelResearchDetailController,
    ChannelResearchImportController,
    ChannelResearchRetryController,
    ChannelResearchValidateSpecController,
)
from server.apps.channel_research.logic.value_objects import (
    ChannelResearchListPayload,
    ChannelResearchListQuery,
)
from server.apps.channel_research.models import ChannelResearchJob


def test_collection_list_jobs_uses_query() -> None:
    controller = ChannelResearchCollectionController()
    service = MagicMock()
    service.list_jobs.return_value = ChannelResearchListPayload(
        items=[],
        next_cursor=None,
        total=0,
    )
    query = ChannelResearchListQuery(
        status='PENDING',
        cursor=None,
        limit=10,
    )
    with patch.object(controller, 'resolve', return_value=service):
        controller.get(parsed_query=query)
    service.list_jobs.assert_called_once_with(
        status='PENDING',
        cursor=None,
        limit=10,
    )


@pytest.mark.parametrize(
    'controller_cls',
    [
        ChannelResearchCollectionController,
        ChannelResearchDetailController,
        ChannelResearchRetryController,
        ChannelResearchValidateSpecController,
        ChannelResearchImportController,
    ],
)
def test_handle_error_delegates_unknown_exceptions(
    controller_cls: type,
) -> None:
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


def test_retry_handle_error_maps_validation_and_missing() -> None:
    controller = ChannelResearchRetryController()
    controller.request = MagicMock()
    endpoint = MagicMock(spec=Endpoint)
    validation = controller.handle_error(
        endpoint,
        MagicMock(spec=ChannelResearchRetryController),
        ValidationError('not retryable'),
    )
    assert validation.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    missing = controller.handle_error(
        endpoint,
        MagicMock(spec=ChannelResearchRetryController),
        ChannelResearchJob.DoesNotExist(),
    )
    assert missing.status_code == HTTPStatus.NOT_FOUND


def test_detail_handle_error_maps_validation_and_missing() -> None:
    controller = ChannelResearchDetailController()
    controller.request = MagicMock()
    endpoint = MagicMock(spec=Endpoint)
    validation = controller.handle_error(
        endpoint,
        MagicMock(spec=ChannelResearchDetailController),
        ValidationError('bad patch'),
    )
    assert validation.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    missing = controller.handle_error(
        endpoint,
        MagicMock(spec=ChannelResearchDetailController),
        ChannelResearchJob.DoesNotExist(),
    )
    assert missing.status_code == HTTPStatus.NOT_FOUND
