from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django_fsm import FSMField

if TYPE_CHECKING:
    from django.http import HttpRequest


class FSMModelAdminMixin:
    """Mixin that automatically makes FSMField fields read-only in the admin.

    FSMField(protected=True) raises AttributeError if Django's form machinery
    tries to set the field via setattr(). Adding FSM fields to readonly_fields
    prevents them from appearing in form cleaned_data entirely.
    """

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        fsm_field_names = [
            f.name
            for f in self.model._meta.concrete_fields  # type: ignore[attr-defined]
            if isinstance(f, FSMField)
        ]
        existing = list(super().get_readonly_fields(request, obj))  # type: ignore[misc]
        return existing + [f for f in fsm_field_names if f not in existing]
