from http import HTTPStatus
from typing import final, override

from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
    BlogPostSummaryPayload,
)
from server.apps.main.models import BlogPost
from server.apps.main.services import BlogPostService
from server.common.di import HasContainer


@final
class BlogPostCreate(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Top level endpoints for the ``BlogPost`` model."""

    def post(
        self,
        parsed_body: Body[BlogPostCreatePayload],
    ) -> BlogPostFullPayload:
        """Create new ``BlogPost`` model."""
        return self.resolve(BlogPostService).create(parsed_body)


@final
class BlogPostGet(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Endpoints that only require a path for ``BlogPost`` models."""

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> BlogPostFullPayload:
        """Return existing ``BlogPost`` model by id."""
        return self.resolve(BlogPostService).get_by_id(self.kwargs['id'])

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        """Handle specific errors for this controller."""
        if isinstance(exc, BlogPost.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Blog post not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )


@final
class BlogPostList(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Returns a summary list of all blog posts."""

    def get(self) -> list[BlogPostSummaryPayload]:
        """List all blog posts, newest first."""
        return self.resolve(BlogPostService).list_all()
