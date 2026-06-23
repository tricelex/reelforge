"""URL routing for prompts DMR API."""

from dmr.routing import path

from server.apps.prompts.api import views

app_name = 'prompts_api'

urlpatterns = [
    path(
        'prompt-templates/',
        views.PromptTemplateCollectionController.as_view(),
        name='prompt-template-collection',
    ),
    path(
        'prompt-templates/<uuid:template_id>/',
        views.PromptTemplateDetailController.as_view(),
        name='prompt-template-detail',
    ),
    path(
        'prompt-templates/<uuid:template_id>/versions/',
        views.PromptVersionCollectionController.as_view(),
        name='prompt-version-collection',
    ),
    path(
        'prompt-templates/<uuid:template_id>/versions/<int:version>/activate/',
        views.PromptVersionActivateController.as_view(),
        name='prompt-version-activate',
    ),
    path(
        'formats/',
        views.StoryFormatCollectionController.as_view(),
        name='story-format-collection',
    ),
    path(
        'formats/<uuid:format_id>/',
        views.StoryFormatDetailController.as_view(),
        name='story-format-detail',
    ),
]
