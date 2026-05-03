from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import extend_schema
from rest_framework.viewsets import ModelViewSet

from reelforge.clipping.models import ClipTimedOverlay
from reelforge.clipping.serializers import ClipTimedOverlaySerializer


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
