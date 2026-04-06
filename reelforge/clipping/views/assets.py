from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from reelforge.clipping.models import ClipMediaAsset
from reelforge.clipping.models import ClipMusicAsset
from reelforge.clipping.models import ClipPost
from reelforge.clipping.models import ClipRenderTemplate
from reelforge.clipping.serializers import ClipMediaAssetSerializer
from reelforge.clipping.serializers import ClipMusicAssetSerializer
from reelforge.clipping.serializers import ClipPostSerializer
from reelforge.clipping.serializers import ClipRenderTemplateSerializer
from reelforge.clipping.tasks import sync_clip_analytics

logger = logging.getLogger("reelforge.clipping.api")


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

    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMediaAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


class ClipMusicAssetViewSet(ModelViewSet):
    queryset = ClipMusicAsset.objects.order_by("genre", "name")
    serializer_class = ClipMusicAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMusicAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


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

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request: Request, pk: str | None = None) -> Response:
        template: ClipRenderTemplate = self.get_object()
        template.is_default = True
        template.save(update_fields=["is_default", "updated_at"])
        return Response(ClipRenderTemplateSerializer(template).data)


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

    @action(detail=True, methods=["post"], url_path="sync-analytics")
    def sync_analytics(self, request: Request, pk: str | None = None) -> Response:
        post: ClipPost = self.get_object()
        sync_clip_analytics.delay(str(post.id))
        return Response({"queued": True})
