from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView

from ***REMOVED***.channels import views as channels_views
from ***REMOVED***.channels.views import SocialAccountViewSet
from ***REMOVED***.users.api.views import CurrentUserView

# DRF Router (non-clipping routes)
router = DefaultRouter()
router.register(r"social-accounts", SocialAccountViewSet, basename="social-account")


urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path("about/", TemplateView.as_view(template_name="pages/about.html"), name="about"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("users/", include("***REMOVED***.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    path(
        "oauth/youtube/callback/",
        channels_views.youtube_oauth_callback,
        name="youtube_oauth_callback",
    ),
    path("app/", include("***REMOVED***.ui.urls", namespace="ui")),
    # API v1
    path("api/v1/", include(router.urls)),
    path("api/v1/", include("***REMOVED***.clipping.api.urls")),
    path("api/v1/auth/login/",         TokenObtainPairView.as_view(),  name="token_obtain_pair"),
    path("api/v1/auth/token-refresh/", TokenRefreshView.as_view(),     name="token_refresh"),
    path("api/v1/auth/logout/",        TokenBlacklistView.as_view(),   name="token_blacklist"),
    path("api/v1/auth/me/",            CurrentUserView.as_view(),      name="current_user"),
    # Legacy API router (users)
    path("api/", include("config.api_router")),
    path("api/auth-token/", include("rest_framework.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]

if settings.DEBUG:
    urlpatterns += [
        path("400/", default_views.bad_request, kwargs={"exception": Exception("Bad Request!")}),
        path("403/", default_views.permission_denied, kwargs={"exception": Exception("Permission Denied")}),
        path("404/", default_views.page_not_found, kwargs={"exception": Exception("Page not Found")}),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls)), *urlpatterns]
