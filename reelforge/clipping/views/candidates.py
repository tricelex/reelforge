from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone
from django_fsm import can_proceed
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.serializers import ClipCandidateDetailSerializer
from ***REMOVED***.clipping.serializers import ClipCandidateListSerializer
from ***REMOVED***.clipping.serializers import ClipLayoutConfigSerializer
from ***REMOVED***.clipping.serializers import ClipStyleConfigSerializer
from ***REMOVED***.clipping.tasks import preview_clip_layout
from ***REMOVED***.clipping.tasks import preview_clip_style

logger = logging.getLogger("***REMOVED***.clipping.api")


class ClipCandidateViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
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

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        reason = request.data.get("reason", "")
        candidate.status = ClipCandidate.CandidateStatus.REJECTED
        candidate.approved = False
        candidate.rejection_reason = reason
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @action(detail=True, methods=["post"], url_path="undo-reject")
    def undo_reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.PROPOSED
        candidate.approved = None
        candidate.rejection_reason = ""
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

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


class ClipLayoutConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipLayoutConfig.objects.select_related("candidate")
    serializer_class = ClipLayoutConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(detail=True, methods=["post"], url_path="reset-crop")
    def reset_crop(self, request: Request, pk: str | None = None) -> Response:
        lc: ClipLayoutConfig = self.get_object()
        lc.manual_crop_x = None
        lc.manual_crop_y = None
        lc.manual_crop_w = None
        lc.manual_crop_h = None
        lc.save(update_fields=["manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at"])
        return Response(ClipLayoutConfigSerializer(lc, context={"request": request}).data)


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
