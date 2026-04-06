from __future__ import annotations

import logging
from typing import Any

from django.http import StreamingHttpResponse
from django_fsm import can_proceed
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.serializers import ClippingJobDetailSerializer
from reelforge.clipping.serializers import ClippingJobListSerializer
from reelforge.clipping.sse import emit_job_event
from reelforge.clipping.sse import job_event_stream
from reelforge.clipping.tasks import download_source_video
from reelforge.clipping.tasks import render_clip
from reelforge.clipping.tasks import transcribe_video

logger = logging.getLogger("reelforge.clipping.api")


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

    @action(detail=True, methods=["post"], url_path="approve-all")
    def approve_all(self, request: Request, pk: str | None = None) -> Response:
        """Approve all PROPOSED candidates on this job."""
        job: ClippingJob = self.get_object()
        from django.utils import timezone

        updated = job.candidates.filter(
            status=ClipCandidate.CandidateStatus.PROPOSED
        ).update(
            status=ClipCandidate.CandidateStatus.APPROVED,
            approved=True,
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        return Response({"approved_count": updated})

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
            from reelforge.clipping.tasks import analyze_clips

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
