"""DMR controllers for uploads and library assets."""

from http import HTTPStatus
from typing import final, override

from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.assets.logic.value_objects import (
    LibraryAssetCreatePayload,
    LibraryAssetListPayload,
    LibraryAssetPayload,
    PresignUploadPayload,
    PresignUploadResultPayload,
)
from server.apps.assets.models import LibraryAsset
from server.apps.assets.services import LibraryAssetService, UploadService
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class PresignUploadController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Issue presigned PUT URLs for direct S3 uploads."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[PresignUploadPayload],
    ) -> PresignUploadResultPayload:
        """Return presigned URL and storage key."""
        require_operator(get_request_user(self.request))
        return self.resolve(UploadService).presign_put(parsed_body)


@final
class LibraryAssetCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and register library assets."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> LibraryAssetListPayload:
        """Return library assets with optional filters."""
        return self.resolve(LibraryAssetService).list_assets(
            kind=self.request.GET.get('kind'),
            channel_id=self.request.GET.get('channel'),
            tag=self.request.GET.get('tags'),
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[LibraryAssetCreatePayload],
    ) -> LibraryAssetPayload:
        """Register a presigned-uploaded object."""
        require_operator(get_request_user(self.request))
        return self.resolve(LibraryAssetService).register_from_key(parsed_body)


@final
class LibraryAssetDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get one library asset."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> LibraryAssetPayload:
        """Return library asset detail."""
        return self.resolve(LibraryAssetService).get_by_id(
            str(self.kwargs['asset_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, LibraryAsset.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Library asset not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint, controller, exc,
        )
