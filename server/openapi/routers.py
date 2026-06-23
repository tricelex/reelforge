"""Tagged DMR routers and OpenAPI schema composition."""

from typing import Final

from django.urls import include
from dmr.openapi import OpenAPIContext, default_config
from dmr.openapi.objects import Components, OpenAPI
from dmr.routing import Router, path

from server.apps.analytics.api import root_urls as analytics_root_urls
from server.apps.analytics.api import urls as analytics_api_urls
from server.apps.assets.api import urls as assets_api_urls
from server.apps.channels.api import urls as channels_api_urls
from server.apps.clips.api import urls as clips_api_urls
from server.apps.core.api import enums_urls as core_enums_urls
from server.apps.core.api import urls as core_api_urls
from server.apps.ideas.api import urls as ideas_api_urls
from server.apps.pipelines.api import urls as pipelines_api_urls
from server.apps.prompts.api import urls as prompts_api_urls
from server.common.openapi_tags import (
    ANALYTICS,
    ASSETS,
    AUTH,
    BLUEPRINTS,
    CAMPAIGNS,
    CHANNELS,
    CHARACTERS,
    CLIP_CONFIG,
    CLIP_POSTS,
    CLIP_SOURCES,
    CLIPS,
    ENUMS,
    IDEAS,
    PIPELINE_CAST,
    PIPELINE_REVIEW,
    PIPELINE_RUNS,
    PROMPTS,
    YOUTUBE,
)

_API_PREFIX: Final = 'api/'


def build_tagged_routers() -> tuple[Router, ...]:
    """Routers with full prefixes and OpenAPI tags for schema generation."""
    return (
        Router('api/auth/', core_api_urls.urlpatterns, tags=[AUTH]),
        Router('api/enums/', core_enums_urls.urlpatterns, tags=[ENUMS]),
        Router(
            'api/analytics/',
            analytics_api_urls.urlpatterns,
            tags=[ANALYTICS],
        ),
        Router('api/', analytics_root_urls.urlpatterns, tags=[ANALYTICS]),
        Router('api/', channels_api_urls.channel_urlpatterns, tags=[CHANNELS]),
        Router('api/', channels_api_urls.youtube_urlpatterns, tags=[YOUTUBE]),
        Router(
            'api/',
            channels_api_urls.character_urlpatterns,
            tags=[CHARACTERS],
        ),
        Router('api/', assets_api_urls.urlpatterns, tags=[ASSETS]),
        Router('api/', prompts_api_urls.urlpatterns, tags=[PROMPTS]),
        Router('api/', ideas_api_urls.urlpatterns, tags=[IDEAS]),
        Router(
            'api/',
            pipelines_api_urls.run_urlpatterns,
            tags=[PIPELINE_RUNS],
        ),
        Router(
            'api/',
            pipelines_api_urls.cast_urlpatterns,
            tags=[PIPELINE_CAST],
        ),
        Router(
            'api/',
            pipelines_api_urls.review_urlpatterns,
            tags=[PIPELINE_REVIEW],
        ),
        Router(
            'api/',
            pipelines_api_urls.blueprint_urlpatterns,
            tags=[BLUEPRINTS],
        ),
        Router('api/', clips_api_urls.candidate_urlpatterns, tags=[CLIPS]),
        Router('api/', clips_api_urls.config_urlpatterns, tags=[CLIP_CONFIG]),
        Router('api/', clips_api_urls.post_urlpatterns, tags=[CLIP_POSTS]),
        Router('api/', clips_api_urls.campaign_urlpatterns, tags=[CAMPAIGNS]),
        Router('api/', clips_api_urls.source_urlpatterns, tags=[CLIP_SOURCES]),
    )


def build_api_schema(
    *,
    context: OpenAPIContext | None = None,
) -> OpenAPI:
    """Build merged OpenAPI schema from tagged domain routers."""
    if context is None:
        context = OpenAPIContext(config=default_config())
    paths = {}
    for tagged_router in build_tagged_routers():
        paths.update(tagged_router.get_schema(context).paths)
    components = Components(
        schemas=context.registries.schema.schemas,
        security_schemes=context.registries.security_scheme.schemes,
    )
    return context.config_merger(paths, components)


def build_api_router() -> Router:
    """Compose the unified API router for Django URL routing."""
    return Router(
        _API_PREFIX,
        [
            path('auth/', include(core_api_urls, namespace='core')),
            path('enums/', include(core_enums_urls, namespace='core_enums')),
            path(
                'analytics/',
                include(analytics_api_urls, namespace='analytics_api'),
            ),
            path('', include(analytics_root_urls, namespace='analytics_root')),
            path('', include(channels_api_urls, namespace='channels_api')),
            path('', include(assets_api_urls, namespace='assets_api')),
            path('', include(prompts_api_urls, namespace='prompts_api')),
            path('', include(ideas_api_urls, namespace='ideas_api')),
            path('', include(pipelines_api_urls, namespace='pipelines_api')),
            path('', include(clips_api_urls, namespace='clips')),
        ],
    )
