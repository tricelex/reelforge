"""Tests for ReelForgeAdmin base configuration."""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_json_widget.widgets import JSONEditorWidget
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget

from server.common.admin import ReelForgeAdmin


def test_reelforge_admin_unfold_defaults() -> None:
    """Base admin enables Unfold UX defaults and widget overrides."""
    assert ReelForgeAdmin.compressed_fields is True
    assert ReelForgeAdmin.warn_unsaved_form is True
    assert ReelForgeAdmin.list_filter_submit is True
    assert ReelForgeAdmin.formfield_overrides[models.TextField]['widget'] is WysiwygWidget
    json_widget = ReelForgeAdmin.formfield_overrides[models.JSONField]['widget']
    assert isinstance(json_widget, JSONEditorWidget)
    assert json_widget.options['mode'] == 'code'
    assert ReelForgeAdmin.formfield_overrides[ArrayField]['widget'] is ArrayWidget
