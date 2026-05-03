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
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from reelforge.clipping.models import ClipRender
from reelforge.clipping.serializers import ClipRenderSerializer
from reelforge.clipping.tasks import render_clip

logger = logging.getLogger("reelforge.clipping.api")


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-renders"],
        summary="List renders (filter by ?candidate=)",
        parameters=[
            OpenApiParameter(
                name="candidate",
                description="Filter renders by ClipCandidate UUID",
                required=False,
                type=str,
            ),
        ],
        responses={200: ClipRenderSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["clipping-renders"],
        summary="Get a render with all stage results",
        responses={200: ClipRenderSerializer},
    ),
)
class ClipRenderViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    queryset = ClipRender.objects.select_related("candidate").prefetch_related("stage_results")
    serializer_class = ClipRenderSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        candidate_id = self.request.query_params.get("candidate")
        if candidate_id:
            qs = qs.filter(candidate_id=candidate_id)
        return qs

    @extend_schema(
        tags=["clipping-renders"],
        summary="Resume a PAUSED_AT_GATE render from the next stage",
        request=None,
        responses={
            200: inline_serializer(
                name="ResumeRenderResponse",
                fields={
                    "resumed": drf_serializers.BooleanField(),
                    "start_from_stage": drf_serializers.IntegerField(),
                },
            ),
            400: OpenApiResponse(description="Render is not paused or paused_at_stage not set"),
        },
    )
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str | None = None) -> Response:
        """Resume a PAUSED_AT_GATE render from the next stage."""
        render: ClipRender = self.get_object()
        if render.status != ClipRender.RenderStatus.PAUSED_AT_GATE:
            return Response(
                {"detail": f"Render is not paused. Current status: {render.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if render.paused_at_stage is None:
            return Response(
                {"detail": "paused_at_stage is not set."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        next_stage = render.paused_at_stage + 1
        render_clip.delay(
            str(render.candidate_id),
            start_from_stage=next_stage,
            clip_render_id=str(render.id),
        )
        return Response({"resumed": True, "start_from_stage": next_stage})

    @extend_schema(
        tags=["clipping-renders"],
        summary="Re-run a render from a specific stage (1–10)",
        request=None,
        responses={
            200: inline_serializer(
                name="RerunRenderResponse",
                fields={
                    "rerunning": drf_serializers.BooleanField(),
                    "start_from_stage": drf_serializers.IntegerField(),
                },
            ),
            400: OpenApiResponse(description="stage_order out of range 1–10"),
        },
    )
    @action(detail=True, methods=["post"], url_path=r"rerun/(?P<stage_order>[0-9]+)")
    def rerun(self, request: Request, pk: str | None = None, stage_order: str = "1") -> Response:
        """Re-run a render from a specific stage."""
        render: ClipRender = self.get_object()
        start = int(stage_order)
        if not 1 <= start <= 10:
            return Response(
                {"detail": "stage_order must be between 1 and 10."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        render_clip.delay(
            str(render.candidate_id),
            start_from_stage=start,
            clip_render_id=str(render.id),
        )
        return Response({"rerunning": True, "start_from_stage": start})

    @extend_schema(
        tags=["clipping-renders"],
        summary="Get download URL for the final rendered video",
        responses={
            200: inline_serializer(
                name="DownloadUrlResponse",
                fields={"download_url": drf_serializers.URLField()},
            ),
            404: OpenApiResponse(description="Render has no video file yet"),
        },
    )
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> Response:
        """Return a URL for downloading the final render file."""
        render: ClipRender = self.get_object()
        if not render.video_file:
            return Response(
                {"detail": "Render has no video file yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        url = request.build_absolute_uri(render.video_file.url)
        return Response({"download_url": url})
