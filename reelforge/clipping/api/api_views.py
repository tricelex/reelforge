from __future__ import annotations

import logging
from typing import Any

from django.http import StreamingHttpResponse
from django.utils import timezone
from django_fsm import can_proceed
from drf_spectacular.types import OpenApiTypes
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
from rest_framework.mixins import UpdateModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.viewsets import ModelViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.api.serializers import ClipCandidateDetailSerializer
from ***REMOVED***.clipping.api.serializers import ClipCandidateListSerializer
from ***REMOVED***.clipping.api.serializers import ClipLayoutConfigSerializer
from ***REMOVED***.clipping.api.serializers import ClipMediaAssetSerializer
from ***REMOVED***.clipping.api.serializers import ClipMusicAssetSerializer
from ***REMOVED***.clipping.api.serializers import ClipPostSerializer
from ***REMOVED***.clipping.api.serializers import ClipRenderSerializer
from ***REMOVED***.clipping.api.serializers import ClipRenderTemplateSerializer
from ***REMOVED***.clipping.api.serializers import ClipStyleConfigSerializer
from ***REMOVED***.clipping.api.serializers import ClipTimedOverlaySerializer
from ***REMOVED***.clipping.api.serializers import ClippingJobDetailSerializer
from ***REMOVED***.clipping.api.serializers import ClippingJobListSerializer
from ***REMOVED***.clipping.sse import emit_job_event
from ***REMOVED***.clipping.sse import job_event_stream
from ***REMOVED***.clipping.tasks import download_source_video
from ***REMOVED***.clipping.tasks import preview_clip_layout
from ***REMOVED***.clipping.tasks import render_clip
from ***REMOVED***.clipping.tasks import sync_clip_analytics
from ***REMOVED***.clipping.tasks import transcribe_video

logger = logging.getLogger("***REMOVED***.clipping.api")


# ── ClippingJob ────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-jobs"],
        summary="List clipping jobs",
        responses={200: ClippingJobListSerializer(many=True)},
    ),
    create=extend_schema(
        tags=["clipping-jobs"],
        summary="Create a clipping job and start download",
        responses={201: ClippingJobDetailSerializer},
    ),
    retrieve=extend_schema(
        tags=["clipping-jobs"],
        summary="Get a clipping job with candidates",
        responses={200: ClippingJobDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["clipping-jobs"],
        summary="Partially update a clipping job",
        responses={200: ClippingJobDetailSerializer},
    ),
    destroy=extend_schema(
        tags=["clipping-jobs"],
        summary="Delete a clipping job",
        responses={204: None},
    ),
)
class ClippingJobViewSet(ModelViewSet):
    queryset = ClippingJob.objects.select_related("social_account").order_by("-created_at")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClippingJobDetailSerializer
        return ClippingJobListSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def perform_create(self, serializer) -> None:
        job: ClippingJob = serializer.save()
        if can_proceed(job.begin_download):
            job.begin_download()
            job.save(update_fields=["status", "started_at", "updated_at"])
        download_source_video.delay(str(job.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        logger.info("ClippingJob created", extra={"job_id": str(job.id)})

    @extend_schema(
        tags=["clipping-jobs"],
        summary="Dispatch render_clip for all approved candidates",
        request=None,
        responses={
            200: inline_serializer(
                name="StartRenderResponse",
                fields={
                    "dispatched_renders": drf_serializers.IntegerField(),
                    "candidate_ids": drf_serializers.ListField(child=drf_serializers.UUIDField()),
                    "job_status": drf_serializers.CharField(),
                },
            ),
            400: OpenApiResponse(description="No approved candidates or invalid FSM state"),
        },
    )
    @action(detail=True, methods=["post"], url_path="start-render")
    def start_render(self, request: Request, pk: str | None = None) -> Response:
        """Dispatch render_clip for all APPROVED candidates and begin_rendering FSM transition."""
        job: ClippingJob = self.get_object()
        approved = list(
            job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED)
        )
        if not approved:
            return Response(
                {"detail": "No approved candidates found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not can_proceed(job.begin_rendering):
            return Response(
                {"detail": f"Cannot begin rendering from state {job.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.begin_rendering()
        job.save(update_fields=["status", "updated_at"])
        for candidate in approved:
            render_clip.delay(str(candidate.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        return Response(
            {
                "dispatched_renders": len(approved),
                "candidate_ids": [str(c.id) for c in approved],
                "job_status": job.status,
            }
        )

    @extend_schema(
        tags=["clipping-jobs"],
        summary="Approve all PROPOSED candidates on this job",
        request=None,
        responses={
            200: inline_serializer(
                name="ApproveAllResponse",
                fields={"approved_count": drf_serializers.IntegerField()},
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="approve-all")
    def approve_all(self, request: Request, pk: str | None = None) -> Response:
        """Approve all PROPOSED candidates on this job."""
        job: ClippingJob = self.get_object()
        updated = job.candidates.filter(
            status=ClipCandidate.CandidateStatus.PROPOSED
        ).update(
            status=ClipCandidate.CandidateStatus.APPROVED,
            approved=True,
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        return Response({"approved_count": updated})

    @extend_schema(
        tags=["clipping-jobs"],
        summary="Retry a failed job from transcription or analysis stage",
        request=inline_serializer(
            name="RetryRequest",
            fields={
                "from_stage": drf_serializers.ChoiceField(
                    choices=["transcription", "analysis"],
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="RetryResponse",
                fields={
                    "job_status": drf_serializers.CharField(),
                    "retrying": drf_serializers.CharField(),
                },
            ),
            400: OpenApiResponse(description="Invalid FSM state for retry"),
        },
    )
    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request: Request, pk: str | None = None) -> Response:
        """Retry a failed job. Body: {"from_stage": "transcription" | "analysis"}"""
        job: ClippingJob = self.get_object()
        from_stage = request.data.get("from_stage", "transcription")
        if from_stage == "analysis":
            if not can_proceed(job.retry_analysis):
                return Response(
                    {"detail": f"Cannot retry analysis from state {job.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.retry_analysis()
            job.save(update_fields=["status", "last_error", "updated_at"])
            from ***REMOVED***.clipping.tasks import analyze_clips

            analyze_clips.delay(str(job.id))
        else:
            if not can_proceed(job.retry_transcription):
                return Response(
                    {"detail": f"Cannot retry transcription from state {job.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.retry_transcription()
            job.save(update_fields=["status", "last_error", "updated_at"])
            transcribe_video.delay(str(job.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        return Response({"job_status": job.status, "retrying": from_stage})

    @extend_schema(
        tags=["clipping-jobs"],
        summary="SSE stream — real-time job events via Redis pub/sub",
        description=(
            "Server-Sent Events stream. Connect with EventSource. "
            "Each event is a JSON payload: `{type, job_id, ...}`. "
            "Event types: status_changed, analysis_complete, job_failed, "
            "render_paused, render_complete, render_failed, post_complete, preview_ready."
        ),
        responses={200: OpenApiTypes.STR},
    )
    @action(detail=True, methods=["get"], url_path="stream")
    def stream(self, request: Request, pk: str | None = None) -> StreamingHttpResponse:
        """SSE endpoint. Streams real-time job events from Redis pub/sub."""
        job: ClippingJob = self.get_object()
        response = StreamingHttpResponse(
            job_event_stream(str(job.id)),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


# ── ClipCandidate ──────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-candidates"],
        summary="List clip candidates (filter by ?job= and ?status=)",
        parameters=[
            OpenApiParameter(name="job", description="Filter by ClippingJob UUID", required=False, type=str),
            OpenApiParameter(
                name="status",
                description="Filter by candidate status",
                required=False,
                type=str,
                enum=["PROPOSED", "APPROVED", "REJECTED", "RENDERING", "RENDERED", "DISTRIBUTING", "DISTRIBUTED"],
            ),
        ],
        responses={200: ClipCandidateListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["clipping-candidates"],
        summary="Get a clip candidate with full layout/style config",
        responses={200: ClipCandidateDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["clipping-candidates"],
        summary="Update clip candidate fields (title, hook_text, render_gates, etc.)",
        responses={200: ClipCandidateDetailSerializer},
    ),
)
class ClipCandidateViewSet(ListModelMixin, RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipCandidate.objects.select_related(
        "clipping_job__social_account",
        "approved_by",
        "layout_config",
        "style_config",
    ).prefetch_related("timed_overlays")
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClipCandidateDetailSerializer
        return ClipCandidateListSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        job_id = self.request.query_params.get("job")
        if job_id:
            qs = qs.filter(clipping_job_id=job_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Approve a clip candidate",
        request=None,
        responses={
            200: inline_serializer(
                name="CandidateApproveResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "status": drf_serializers.CharField(),
                    "approved": drf_serializers.BooleanField(),
                    "approved_at": drf_serializers.DateTimeField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.APPROVED
        candidate.approved = True
        candidate.approved_at = timezone.now()
        candidate.approved_by = request.user
        candidate.save(update_fields=["status", "approved", "approved_at", "approved_by", "updated_at"])
        return Response({
            "id": str(candidate.id),
            "status": candidate.status,
            "approved": candidate.approved,
            "approved_at": candidate.approved_at,
        })

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Reject a clip candidate",
        request=inline_serializer(
            name="CandidateRejectRequest",
            fields={"reason": drf_serializers.CharField(required=False, default="")},
        ),
        responses={
            200: inline_serializer(
                name="CandidateRejectResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "status": drf_serializers.CharField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        reason = request.data.get("reason", "")
        candidate.status = ClipCandidate.CandidateStatus.REJECTED
        candidate.approved = False
        candidate.rejection_reason = reason
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Undo rejection — reset candidate to PROPOSED",
        request=None,
        responses={
            200: inline_serializer(
                name="UndoRejectResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "status": drf_serializers.CharField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="undo-reject")
    def undo_reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.PROPOSED
        candidate.approved = None
        candidate.rejection_reason = ""
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Queue a layout preview image generation task",
        request=None,
        responses={
            200: inline_serializer(
                name="TriggerPreviewResponse",
                fields={
                    "queued": drf_serializers.BooleanField(),
                    "layout_config_id": drf_serializers.UUIDField(),
                },
            ),
            400: OpenApiResponse(description="No layout config found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="trigger-preview")
    def trigger_preview(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        if not hasattr(candidate, "layout_config"):
            return Response(
                {"detail": "No layout config found for this candidate."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        preview_clip_layout.delay(str(candidate.layout_config.id))
        return Response({"queued": True, "layout_config_id": str(candidate.layout_config.id)})

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Check if layout preview image is ready",
        responses={
            200: inline_serializer(
                name="PreviewStatusResponse",
                fields={
                    "ready": drf_serializers.BooleanField(),
                    "preview_url": drf_serializers.URLField(allow_null=True),
                },
            ),
        },
    )
    @action(detail=True, methods=["get"], url_path="preview-status")
    def preview_status(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        lc = getattr(candidate, "layout_config", None)
        if lc is None:
            return Response({"ready": False, "preview_url": None})
        preview_url = None
        if lc.preview_image:
            preview_url = request.build_absolute_uri(lc.preview_image.url)
        return Response({"ready": bool(lc.preview_image), "preview_url": preview_url})


# ── ClipLayoutConfig ───────────────────────────────────────────────────────────


@extend_schema_view(
    retrieve=extend_schema(
        tags=["clipping-candidates"],
        summary="Get layout config for a candidate",
    ),
    partial_update=extend_schema(
        tags=["clipping-candidates"],
        summary="Update layout config (render_mode, crop coords, stack regions)",
    ),
)
class ClipLayoutConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipLayoutConfig.objects.select_related("candidate")
    serializer_class = ClipLayoutConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Clear manual crop coordinates (reset to auto-detect)",
        request=None,
        responses={200: ClipLayoutConfigSerializer},
    )
    @action(detail=True, methods=["post"], url_path="reset-crop")
    def reset_crop(self, request: Request, pk: str | None = None) -> Response:
        lc: ClipLayoutConfig = self.get_object()
        lc.manual_crop_x = None
        lc.manual_crop_y = None
        lc.manual_crop_w = None
        lc.manual_crop_h = None
        lc.save(update_fields=["manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at"])
        return Response(ClipLayoutConfigSerializer(lc, context={"request": request}).data)


# ── ClipStyleConfig ────────────────────────────────────────────────────────────


@extend_schema_view(
    retrieve=extend_schema(
        tags=["clipping-candidates"],
        summary="Get style config for a candidate",
    ),
    partial_update=extend_schema(
        tags=["clipping-candidates"],
        summary="Update style config (captions, watermark, music, etc.)",
    ),
)
class ClipStyleConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipStyleConfig.objects.select_related(
        "candidate", "render_template", "intro_asset", "outro_asset", "music_asset"
    )
    serializer_class = ClipStyleConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Re-seed all style fields from a render template",
        request=inline_serializer(
            name="ApplyTemplateRequest",
            fields={"template_id": drf_serializers.UUIDField()},
        ),
        responses={
            200: ClipStyleConfigSerializer,
            400: OpenApiResponse(description="template_id is required"),
            404: OpenApiResponse(description="Template not found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="apply-template")
    def apply_template(self, request: Request, pk: str | None = None) -> Response:
        """Re-seed all style fields from a given render template."""
        config: ClipStyleConfig = self.get_object()
        template_id = request.data.get("template_id")
        if not template_id:
            return Response(
                {"detail": "template_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            template = ClipRenderTemplate.objects.get(id=template_id)
        except ClipRenderTemplate.DoesNotExist:
            return Response({"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND)

        style_fields = template.to_style_defaults()
        for field_name, value in style_fields.items():
            setattr(config, field_name, value)
        config.render_template = template
        config.save(update_fields=[*style_fields.keys(), "render_template", "updated_at"])
        return Response(ClipStyleConfigSerializer(config, context={"request": request}).data)


# ── ClipRender ─────────────────────────────────────────────────────────────────


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


# ── ClipTimedOverlay ───────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-overlays"],
        summary="List timed overlays (filter by ?candidate=)",
        parameters=[
            OpenApiParameter(
                name="candidate",
                description="Filter by ClipCandidate UUID",
                required=False,
                type=str,
            ),
        ],
    ),
    create=extend_schema(tags=["clipping-overlays"], summary="Create a timed overlay"),
    retrieve=extend_schema(tags=["clipping-overlays"], summary="Get a timed overlay"),
    partial_update=extend_schema(tags=["clipping-overlays"], summary="Update a timed overlay"),
    destroy=extend_schema(tags=["clipping-overlays"], summary="Delete a timed overlay"),
)
class ClipTimedOverlayViewSet(ModelViewSet):
    queryset = ClipTimedOverlay.objects.select_related("candidate")
    serializer_class = ClipTimedOverlaySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        candidate_id = self.request.query_params.get("candidate")
        if candidate_id:
            qs = qs.filter(candidate_id=candidate_id)
        return qs


# ── ClipMediaAsset ─────────────────────────────────────────────────────────────


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


# ── ClipMusicAsset ─────────────────────────────────────────────────────────────


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


# ── ClipRenderTemplate ─────────────────────────────────────────────────────────


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


# ── ClipPost ───────────────────────────────────────────────────────────────────


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
