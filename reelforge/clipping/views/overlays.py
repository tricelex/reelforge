from __future__ import annotations

from rest_framework.viewsets import ModelViewSet

from ***REMOVED***.clipping.models import ClipTimedOverlay
from ***REMOVED***.clipping.serializers import ClipTimedOverlaySerializer


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
