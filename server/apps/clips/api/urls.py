"""URL routing for the clips API."""

from dmr.routing import path

from server.apps.clips.api import (
    brand_template_views,
    campaign_views,
    source_views,
    views,
)

app_name = 'clips'

candidate_urlpatterns = [
    path(
        'runs/<uuid:run_id>/candidates/',
        views.ClipCandidateListView.as_view(),
        name='candidate_list',
    ),
    path(
        'runs/<uuid:run_id>/candidates/approve-all/',
        views.ClipCandidateApproveAllView.as_view(),
        name='candidate_approve_all',
    ),
    path(
        'runs/<uuid:run_id>/start-render/',
        views.ClipStartRenderView.as_view(),
        name='start_render',
    ),
    path(
        'candidates/<uuid:candidate_id>/',
        views.ClipCandidateDetailView.as_view(),
        name='candidate_detail',
    ),
    path(
        'candidates/<uuid:candidate_id>/render/',
        views.ClipCandidateRenderView.as_view(),
        name='candidate_render',
    ),
    path(
        'candidates/<uuid:candidate_id>/preview/',
        views.ClipCandidatePreviewView.as_view(),
        name='candidate_preview',
    ),
    path(
        'candidates/<uuid:candidate_id>/preview/status/',
        views.ClipCandidatePreviewStatusView.as_view(),
        name='candidate_preview_status',
    ),
    path(
        'candidates/<uuid:candidate_id>/approve/',
        views.ClipCandidateApproveView.as_view(),
        name='candidate_approve',
    ),
    path(
        'candidates/<uuid:candidate_id>/reject/',
        views.ClipCandidateRejectView.as_view(),
        name='candidate_reject',
    ),
    path(
        'candidates/<uuid:candidate_id>/duplicate/',
        views.ClipCandidateDuplicateView.as_view(),
        name='candidate_duplicate',
    ),
    path(
        'caption-presets/',
        views.CaptionPresetListView.as_view(),
        name='caption_presets',
    ),
]

config_urlpatterns = [
    path(
        'candidates/<uuid:candidate_id>/layout-config/',
        views.ClipLayoutConfigView.as_view(),
        name='layout_config',
    ),
    path(
        'candidates/<uuid:candidate_id>/layout-config/smart-crop/',
        views.ClipLayoutSmartCropView.as_view(),
        name='layout_config_smart_crop',
    ),
    path(
        'candidates/<uuid:candidate_id>/source-frame/',
        views.ClipCandidateSourceFrameView.as_view(),
        name='candidate_source_frame',
    ),
    path(
        'candidates/<uuid:candidate_id>/style-config/',
        views.ClipStyleConfigView.as_view(),
        name='style_config',
    ),
    path(
        'candidates/<uuid:candidate_id>/overlays/',
        views.ClipTimedOverlayCollectionView.as_view(),
        name='overlay_list',
    ),
    path(
        'candidates/<uuid:candidate_id>/overlays/<uuid:overlay_id>/',
        views.ClipTimedOverlayDetailView.as_view(),
        name='overlay_detail',
    ),
    path(
        'candidates/<uuid:candidate_id>/sfx/',
        views.ClipTimedSfxCollectionView.as_view(),
        name='sfx_list',
    ),
    path(
        'candidates/<uuid:candidate_id>/sfx/<uuid:sfx_id>/',
        views.ClipTimedSfxDetailView.as_view(),
        name='sfx_detail',
    ),
]

post_urlpatterns = [
    path(
        'candidates/<uuid:candidate_id>/posts/',
        views.ClipPostCollectionView.as_view(),
        name='post_list',
    ),
    path(
        'candidates/<uuid:candidate_id>/posts/<uuid:post_id>/',
        views.ClipPostDetailView.as_view(),
        name='post_detail',
    ),
]

campaign_urlpatterns = [
    path(
        'campaigns/',
        campaign_views.CampaignCollectionController.as_view(),
        name='campaign-collection',
    ),
    path(
        'campaigns/<uuid:campaign_id>/',
        campaign_views.CampaignDetailController.as_view(),
        name='campaign-detail',
    ),
    path(
        'earnings/',
        campaign_views.EarningCollectionController.as_view(),
        name='earning-collection',
    ),
]

source_urlpatterns = [
    path(
        'clip-sources/',
        source_views.ClipSourceCollectionController.as_view(),
        name='clip-source-collection',
    ),
    path(
        'clip-sources/<uuid:source_id>/',
        source_views.ClipSourceDetailController.as_view(),
        name='clip-source-detail',
    ),
]

brand_template_urlpatterns = [
    path(
        'brand-templates/',
        brand_template_views.BrandTemplateCollectionController.as_view(),
        name='brand-template-collection',
    ),
    path(
        'brand-templates/<uuid:template_id>/',
        brand_template_views.BrandTemplateDetailController.as_view(),
        name='brand-template-detail',
    ),
    path(
        'brand-templates/<uuid:template_id>/duplicate/',
        brand_template_views.BrandTemplateDuplicateController.as_view(),
        name='brand-template-duplicate',
    ),
]

urlpatterns = [
    *candidate_urlpatterns,
    *config_urlpatterns,
    *post_urlpatterns,
    *campaign_urlpatterns,
    *source_urlpatterns,
    *brand_template_urlpatterns,
]
