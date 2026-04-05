from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views import View


@method_decorator(staff_member_required, name="dispatch")
class StaffRequiredMixin(View):
    """Mixin that restricts access to staff members only.

    Apply as the first base class: class MyView(StaffRequiredMixin, TemplateView).
    Redirects non-staff to /admin/login/ (Django default for staff_member_required).
    """
