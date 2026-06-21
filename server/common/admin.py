"""Shared Django Unfold admin base for ReelForge."""

from typing import ClassVar

from django.contrib.postgres.fields import ArrayField
from django.db import models
from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget


class ReelForgeAdmin(ModelAdmin):  # type: ignore[misc]
    """Base ModelAdmin with Unfold defaults used across all ReelForge admins."""

    compressed_fields = True
    warn_unsaved_form = True
    list_filter_submit = True
    formfield_overrides: ClassVar = {
        models.TextField: {
            'widget': WysiwygWidget,
        },
        ArrayField: {
            'widget': ArrayWidget,
        },
    }
