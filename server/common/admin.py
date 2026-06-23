"""Shared Django Unfold admin base for ReelForge."""

from typing import ClassVar

from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget

_JSON_EDITOR_WIDGET = JSONEditorWidget(
    options={
        'mode': 'code',
        'modes': ['code', 'tree'],
        'search': True,
    },
)


class ReelForgeAdmin(ModelAdmin):  # type: ignore[misc]
    """Base ModelAdmin with Unfold defaults used across all ReelForge admins."""

    compressed_fields = True
    warn_unsaved_form = True
    list_filter_submit = True
    formfield_overrides: ClassVar = {
        models.TextField: {
            'widget': WysiwygWidget,
        },
        models.JSONField: {
            'widget': _JSON_EDITOR_WIDGET,
        },
        ArrayField: {
            'widget': ArrayWidget,
        },
    }
