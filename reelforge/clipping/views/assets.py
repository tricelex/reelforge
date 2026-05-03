from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.serializers import ClipMediaAssetSerializer
from ***REMOVED***.clipping.serializers import ClipMusicAssetSerializer
from ***REMOVED***.clipping.serializers import ClipPostSerializer
from ***REMOVED***.clipping.serializers import ClipRenderTemplateSerializer
from ***REMOVED***.clipping.tasks import sync_clip_analytics

logger = logging.getLogger("***REMOVED***.clipping.api")


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-assets"],
        summary="List media assets (filter by ?asset_type=INTRO or OUTRO)",
        parameters=[
            OpenApiParameter(
                name="asset_type",
                description="Filter by asset type",
                required=False,
                type=str,
                enum=["INTRO", "OUTRO"],
            ),
        ],
    ),
    create=extend_schema(tags=["clipping-assets"], summary="Upload a media asset"),
    retrieve=extend_schema(tags=["clipping-assets"], summary="Get a media asset"),
    partial_update=extend_schema(tags=["clipping-assets"], summary="Update a media asset"),
    destroy=extend_schema(tags=["clipping-assets"], summary="Delete a media asset"),
)
class ClipMediaAssetViewSet(ModelViewSet):
    queryset = ClipMediaAsset.objects.order_by("asset_type", "name")
    serializer_class = ClipMediaAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        asset_type = self.request.query_params.get("asset_type")
        if asset_type:
            qs = qs.filter(asset_type=asset_type)
        return qs

    @extend_schema(
        tags=["clipping-assets"],
        summary="Get a direct URL for the media asset file",
        responses={
            200: inline_serializer(
                name="MediaAssetPreviewUrlResponse",
                fields={"url": drf_serializers.URLField()},
            ),
            404: OpenApiResponse(description="Asset has no file"),
        },
    )
    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMediaAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


@extend_schema_view(
    list=extend_schema(tags=["clipping-assets"], summary="List music assets"),
    create=extend_schema(tags=["clipping-assets"], summary="Upload a music asset"),
    retrieve=extend_schema(tags=["clipping-assets"], summary="Get a music asset"),
    partial_update=extend_schema(tags=["clipping-assets"], summary="Update a music asset"),
    destroy=extend_schema(tags=["clipping-assets"], summary="Delete a music asset"),
)
class ClipMusicAssetViewSet(ModelViewSet):
    queryset = ClipMusicAsset.objects.order_by("genre", "name")
    serializer_class = ClipMusicAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["clipping-assets"],
        summary="Get a direct URL for the music asset file",
        responses={
            200: inline_serializer(
                name="MusicAssetPreviewUrlResponse",
                fields={"url": drf_serializers.URLField()},
            ),
            404: OpenApiResponse(description="Asset has no file"),
        },
    )
    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMusicAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


@extend_schema_view(
    list=extend_schema(tags=["clipping-assets"], summary="List render templates"),
    create=extend_schema(tags=["clipping-assets"], summary="Create a render template"),
    retrieve=extend_schema(tags=["clipping-assets"], summary="Get a render template"),
    partial_update=extend_schema(tags=["clipping-assets"], summary="Update a render template"),
    destroy=extend_schema(tags=["clipping-assets"], summary="Delete a render template (blocked if is_default=True)"),
)
class ClipRenderTemplateViewSet(ModelViewSet):
    queryset = ClipRenderTemplate.objects.order_by("-is_default", "name")
    serializer_class = ClipRenderTemplateSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        template: ClipRenderTemplate = self.get_object()
        if template.is_default:
            return Response(
                {"detail": "Cannot delete the default render template."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        tags=["clipping-assets"],
        summary="Set this template as the default render template",
        request=None,
        responses={200: ClipRenderTemplateSerializer},
    )
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request: Request, pk: str | None = None) -> Response:
        template: ClipRenderTemplate = self.get_object()
        template.is_default = True
        template.save(update_fields=["is_default", "updated_at"])
        return Response(ClipRenderTemplateSerializer(template).data)


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-posts"],
        summary="List clip posts (filter by ?render=)",
        parameters=[
            OpenApiParameter(
                name="render",
                description="Filter by ClipRender UUID",
                required=False,
                type=str,
            ),
        ],
    ),
    retrieve=extend_schema(tags=["clipping-posts"], summary="Get a clip post"),
)
class ClipPostViewSet(ReadOnlyModelViewSet):
    queryset = ClipPost.objects.select_related("render", "social_account")
    serializer_class = ClipPostSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        render_id = self.request.query_params.get("render")
        if render_id:
            qs = qs.filter(render_id=render_id)
        return qs

    @extend_schema(
        tags=["clipping-posts"],
        summary="Queue an analytics sync for this clip post",
        request=None,
        responses={
            200: inline_serializer(
                name="SyncAnalyticsResponse",
                fields={"queued": drf_serializers.BooleanField()},
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="sync-analytics")
    def sync_analytics(self, request: Request, pk: str | None = None) -> Response:
        post: ClipPost = self.get_object()
        sync_clip_analytics.delay(str(post.id))
        return Response({"queued": True})
