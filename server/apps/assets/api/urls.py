"""URL routing for assets DMR API."""

from dmr.routing import path

from server.apps.assets.api import views

app_name = 'assets_api'

urlpatterns = [
    path(
        'uploads/presign/',
        views.PresignUploadController.as_view(),
        name='upload-presign',
    ),
    path(
        'library-assets/',
        views.LibraryAssetCollectionController.as_view(),
        name='library-asset-collection',
    ),
    path(
        'library-assets/<uuid:asset_id>/',
        views.LibraryAssetDetailController.as_view(),
        name='library-asset-detail',
    ),
]
