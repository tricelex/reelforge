from __future__ import annotations

from rest_framework.routers import DefaultRouter

from ***REMOVED***.clipping.api.api_views import ClipCandidateViewSet
from ***REMOVED***.clipping.api.api_views import ClipLayoutConfigViewSet
from ***REMOVED***.clipping.api.api_views import ClipMediaAssetViewSet
from ***REMOVED***.clipping.api.api_views import ClipMusicAssetViewSet
from ***REMOVED***.clipping.api.api_views import ClipPostViewSet
from ***REMOVED***.clipping.api.api_views import ClipRenderTemplateViewSet
from ***REMOVED***.clipping.api.api_views import ClipRenderViewSet
from ***REMOVED***.clipping.api.api_views import ClipStyleConfigViewSet
from ***REMOVED***.clipping.api.api_views import ClipTimedOverlayViewSet
from ***REMOVED***.clipping.api.api_views import ClippingJobViewSet

router = DefaultRouter()
router.register(r"clipping/jobs",             ClippingJobViewSet,         basename="clipping-job")
router.register(r"clipping/candidates",       ClipCandidateViewSet,       basename="clip-candidate")
router.register(r"clipping/renders",          ClipRenderViewSet,          basename="clip-render")
router.register(r"clipping/layout-configs",   ClipLayoutConfigViewSet,    basename="clip-layout")
router.register(r"clipping/style-configs",    ClipStyleConfigViewSet,     basename="clip-style")
router.register(r"clipping/overlays",         ClipTimedOverlayViewSet,    basename="clip-overlay")
router.register(r"clipping/media-assets",     ClipMediaAssetViewSet,      basename="clip-media-asset")
router.register(r"clipping/music-assets",     ClipMusicAssetViewSet,      basename="clip-music-asset")
router.register(r"clipping/render-templates", ClipRenderTemplateViewSet,  basename="clip-render-template")
router.register(r"clipping/posts",            ClipPostViewSet,            basename="clip-post")

urlpatterns = router.urls
