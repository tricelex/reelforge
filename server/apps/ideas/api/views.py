"""DMR controllers for ideation APIs."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.core.auth import require_operator
from server.apps.ideas.logic.value_objects import (
    IdeaGeneratePayload,
    IdeaListPayload,
    PromoteIdeaResultPayload,
    TopicIdeaPatchPayload,
    TopicIdeaPayload,
)
from server.apps.ideas.models import TopicIdea
from server.apps.ideas.selectors import get_idea
from server.apps.ideas.services import IdeationService
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class IdeaCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List backlog ideas."""

    auth = (jwt_sync_auth,)

    def get(self) -> IdeaListPayload:
        """Return cursor-paginated ideas."""
        status = self.request.GET.get('status')
        channel_id = self.request.GET.get('channel_id')
        cursor = self.request.GET.get('cursor')
        limit_raw = self.request.GET.get('limit', '20')
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 20
        return self.resolve(IdeationService).list_backlog(
            status=status,
            channel_id=channel_id,
            cursor=cursor,
            limit=limit,
        )


@final
class IdeaDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Patch one backlog idea."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> TopicIdeaPayload:
        """Return one backlog idea."""
        return get_idea(str(self.kwargs['idea_id']))

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def patch(
        self,
        parsed_body: Body[TopicIdeaPatchPayload],
    ) -> TopicIdeaPayload:
        """Update idea fields."""
        require_operator(get_request_user(self.request))
        return self.resolve(IdeationService).patch(
            str(self.kwargs['idea_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        if isinstance(exc, TopicIdea.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Idea not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class NicheIdeaGenerateController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Batch-generate ideas for a niche."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[IdeaGeneratePayload],
    ) -> IdeaListPayload:
        """Generate backlog ideas."""
        require_operator(get_request_user(self.request))
        return self.resolve(IdeationService).generate(
            str(self.kwargs['niche_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class IdeaPromoteController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Promote an idea into a pipeline run."""

    auth = (jwt_sync_auth,)

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def post(self) -> PromoteIdeaResultPayload:
        """Create a run from a backlog idea."""
        require_operator(get_request_user(self.request))
        return self.resolve(IdeationService).promote(
            str(self.kwargs['idea_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        if isinstance(exc, TopicIdea.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Idea not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)
