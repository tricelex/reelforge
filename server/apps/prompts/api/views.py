"""DMR controllers for prompts and story formats."""

from http import HTTPStatus
from typing import final, override

from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.core.auth import require_operator
from server.apps.prompts.logic.value_objects import (
    PromptTemplateCreatePayload,
    PromptTemplateDetailPayload,
    PromptTemplateListPayload,
    PromptTemplatePatchPayload,
    PromptVersionCreatePayload,
    PromptVersionListPayload,
    PromptVersionPayload,
    StoryFormatCreatePayload,
    StoryFormatListPayload,
    StoryFormatPatchPayload,
    StoryFormatPayload,
)
from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)
from server.apps.prompts.selectors import (
    get_prompt_template,
    get_story_format,
    list_prompt_templates,
    list_prompt_versions,
    list_story_formats,
)
from server.apps.prompts.services import (
    PromptTemplateService,
    StoryFormatService,
)
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class PromptTemplateCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create prompt templates."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> PromptTemplateListPayload:
        """Return paginated prompt templates."""
        return list_prompt_templates(
            scope=self.request.GET.get('scope'),
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[PromptTemplateCreatePayload],
    ) -> PromptTemplateDetailPayload:
        """Create a prompt template."""
        require_operator(get_request_user(self.request))
        return self.resolve(PromptTemplateService).create(parsed_body)


@final
class PromptTemplateDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch a prompt template."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> PromptTemplateDetailPayload:
        """Return template detail."""
        return get_prompt_template(str(self.kwargs['template_id']))

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
        parsed_body: Body[PromptTemplatePatchPayload],
    ) -> PromptTemplateDetailPayload:
        """Update template metadata."""
        require_operator(get_request_user(self.request))
        return self.resolve(PromptTemplateService).patch(
            str(self.kwargs['template_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, PromptTemplate.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Prompt template not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class PromptVersionCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create prompt versions."""

    auth = (jwt_sync_auth,)

    def get(self) -> PromptVersionListPayload:
        """Return versions for a template."""
        return list_prompt_versions(str(self.kwargs['template_id']))

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[PromptVersionCreatePayload],
    ) -> PromptVersionPayload:
        """Create a new version."""
        require_operator(get_request_user(self.request))
        return self.resolve(PromptTemplateService).create_version(
            str(self.kwargs['template_id']),
            parsed_body,
        )


@final
class PromptVersionActivateController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Activate a prompt version."""

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
    def post(self) -> PromptVersionPayload:
        """Mark one version active."""
        require_operator(get_request_user(self.request))
        return self.resolve(PromptTemplateService).activate_version(
            str(self.kwargs['template_id']),
            int(self.kwargs['version']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, PromptVersion.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Prompt version not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class StoryFormatCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create story formats."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> StoryFormatListPayload:
        """Return paginated story formats."""
        active_only = self.request.GET.get('active') == 'true'
        return list_story_formats(
            active_only=active_only,
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[StoryFormatCreatePayload],
    ) -> StoryFormatPayload:
        """Create a story format."""
        require_operator(get_request_user(self.request))
        return self.resolve(StoryFormatService).create(parsed_body)


@final
class StoryFormatDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch a story format."""

    auth = (jwt_sync_auth,)

    def get(self) -> StoryFormatPayload:
        """Return format detail."""
        return get_story_format(str(self.kwargs['format_id']))

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
        parsed_body: Body[StoryFormatPatchPayload],
    ) -> StoryFormatPayload:
        """Update a story format."""
        require_operator(get_request_user(self.request))
        return self.resolve(StoryFormatService).patch(
            str(self.kwargs['format_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, StoryFormat.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Story format not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)
