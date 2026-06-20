"""
Main URL mapping configuration file.

Include other URLConfs from external apps using method `include()`.

It is also a good practice to keep a single URL to the root index page.

This examples uses Django's default media
files serving technique in development.
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.admindocs import urls as admindocs_urls
from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from django.views.generic import TemplateView
from dmr.openapi.views import (
    OpenAPIJsonView,
    RedocView,
    ScalarView,
    StoplightView,
    SwaggerView,
)
from dmr.openapi.views.yaml import OpenAPIYamlView
from dmr.plugins.msgspec import MsgspecSerializer
from dmr.routing import build_404_handler, build_500_handler
from health_check.views import HealthCheckView

from server.apps.clips.api import urls as clips_api_urls
from server.apps.main import urls as main_urls
from server.apps.main.api import urls as main_api_urls
from server.apps.main.views import index
from server.openapi.routers import build_api_router, build_api_schema

admin.autodiscover()


def trigger_error(request: HttpRequest) -> HttpResponse:
    """Trigger a deliberate division-by-zero error for Sentry testing."""
    raise ZeroDivisionError


router = build_api_router()
schema = build_api_schema()

handler404 = build_404_handler(router.prefix, serializer=MsgspecSerializer)
handler500 = build_500_handler(router.prefix, serializer=MsgspecSerializer)

urlpatterns = [
    # Apps:
    path('main/', include(main_urls, namespace='main')),
    # Apis:
    path(router.prefix, include((router.urls, 'server'), namespace='api')),
    # Demo blog API (outside unified OpenAPI router):
    path(
        'api/user/',
        include((main_api_urls, 'main_api'), namespace='main_api'),
    ),
    # Legacy clip prefix (deprecated — same handlers as unified /api/):
    path('api/clips/', include(clips_api_urls, namespace='clips_legacy')),
    # OpenAPI:
    path(
        'docs/openapi.json/',
        OpenAPIJsonView.as_view(schema),
        name='openapi_json',
    ),
    path(
        'docs/openapi.yaml/',
        OpenAPIYamlView.as_view(schema),
        name='openapi_yaml',
    ),
    path('docs/stoplight/', StoplightView.as_view(schema), name='stoplight'),
    path('docs/swagger/', SwaggerView.as_view(schema), name='swagger'),
    path('docs/scalar/', ScalarView.as_view(schema), name='scalar'),
    path('docs/redoc/', RedocView.as_view(schema), name='redoc'),
    path('sentry-debug/', trigger_error),
    # Health checks:
    path(
        'health/',
        HealthCheckView.as_view(
            checks=[
                'health_check.Cache',
                'health_check.Database',
                'health_check.Storage',
            ],
        ),
        name='health_check',
    ),
    # django-admin:
    path('admin/doc/', include(admindocs_urls)),
    path('admin/', admin.site.urls),
    # Text and xml static files:
    path(
        'robots.txt',
        TemplateView.as_view(
            template_name='common/txt/robots.txt',
            content_type='text/plain',
        ),
        name='robots_txt',
    ),
    path(
        'humans.txt',
        TemplateView.as_view(
            template_name='common/txt/humans.txt',
            content_type='text/plain',
        ),
        name='humans_txt',
    ),
    # It is a good practice to have explicit index view:
    path('', index, name='index'),
]

if settings.DEBUG:  # pragma: no cover
    import debug_toolbar
    from django.conf.urls.static import static

    urlpatterns = [
        # URLs specific only to django-debug-toolbar:
        path('__debug__/', include(debug_toolbar.urls)),
        *urlpatterns,
        # Serving media files in development only:
        *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
    ]
