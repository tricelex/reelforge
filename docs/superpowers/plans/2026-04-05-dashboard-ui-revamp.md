# Dashboard UI Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current hand-rolled Tailwind dashboard with the Modernize template — full shell, dark theme, 270px sidebar — while converting all FBVs to CBVs and keeping all existing functionality intact.

**Architecture:** Copy `theme.css` and Preline/Simplebar libs from `mode-template/` into Django static files. Rewrite `ui/base.html` using the Modernize HTML structure. Convert every FBV to a CBV using a `StaffRequiredMixin`. Rewrite all page templates to use template CSS classes (`card`, `badge-md`, `divide-border`, etc.) from `theme.css`. No new features, no URL changes.

**Tech Stack:** Django 5.2 CBVs, `theme.css` (Modernize), Preline UI (sidebar JS), Tabler Icons (CDN), HTMX 2.0.4, Alpine.js 3.14, Plus Jakarta Sans (Google Fonts)

**Spec:** `docs/superpowers/specs/2026-04-05-dashboard-ui-revamp-design.md`

---

## File Map

**Create:**
- `***REMOVED***/static/vendor/modernize/css/theme.css` — Modernize compiled CSS
- `***REMOVED***/static/vendor/modernize/libs/preline/preline.js` — Preline UI (sidebar/dropdown JS)
- `***REMOVED***/static/vendor/modernize/libs/simplebar/simplebar.min.css` — sidebar scroll CSS
- `***REMOVED***/static/vendor/modernize/libs/simplebar/simplebar.min.js` — sidebar scroll JS
- `***REMOVED***/ui/mixins.py` — `StaffRequiredMixin` for all CBVs
- `***REMOVED***/ui/tests/test_views.py` — view-level tests for ui app

**Rewrite (full replacement):**
- `***REMOVED***/ui/templates/ui/base.html` — Modernize shell (sidebar + topbar + content)
- `***REMOVED***/ui/templates/ui/dashboard.html` — stats cards + active jobs table + needs attention
- `***REMOVED***/ui/templates/ui/partials/active_jobs.html` — HTMX-polled active jobs table rows
- `***REMOVED***/ui/templates/ui/partials/status_badge.html` — `badge-md` template classes
- `***REMOVED***/ui/views.py` — `DashboardView`, `ActiveJobsPartialView` (CBVs)
- `***REMOVED***/ui/urls.py` — use `.as_view()`
- `***REMOVED***/clipping/views/jobs.py` — `JobListView`, `JobDetailView`, `JobStatusPartialView` (CBVs)
- `***REMOVED***/clipping/views/candidates.py` — all candidate action views as CBVs
- `***REMOVED***/clipping/views/renders.py` — `RenderDetailView`, `StageListPartialView`, `RerunFromStageView`, `ResumeRenderView` (CBVs)
- `***REMOVED***/clipping/urls.py` — use `.as_view()`
- `***REMOVED***/clipping/templates/clipping/job_list.html` — Modernize table
- `***REMOVED***/clipping/templates/clipping/job_detail.html` — Modernize cards + table
- `***REMOVED***/clipping/templates/clipping/render_detail.html` — Modernize cards

---

## Task 1: Copy Static Assets and Update .gitignore

**Files:**
- Create: `***REMOVED***/static/vendor/modernize/css/theme.css`
- Create: `***REMOVED***/static/vendor/modernize/libs/preline/preline.js`
- Create: `***REMOVED***/static/vendor/modernize/libs/simplebar/simplebar.min.css`
- Create: `***REMOVED***/static/vendor/modernize/libs/simplebar/simplebar.min.js`
- Modify: `.gitignore`

- [ ] **Step 1: Copy theme.css**

```bash
mkdir -p ***REMOVED***/static/vendor/modernize/css
cp mode-template/assets/css/theme.css ***REMOVED***/static/vendor/modernize/css/theme.css
```

- [ ] **Step 2: Copy Preline and Simplebar**

```bash
mkdir -p ***REMOVED***/static/vendor/modernize/libs/preline
mkdir -p ***REMOVED***/static/vendor/modernize/libs/simplebar
cp mode-template/assets/libs/preline/dist/preline.js ***REMOVED***/static/vendor/modernize/libs/preline/preline.js
cp mode-template/assets/libs/simplebar/dist/simplebar.min.css ***REMOVED***/static/vendor/modernize/libs/simplebar/simplebar.min.css
cp mode-template/assets/libs/simplebar/dist/simplebar.min.js ***REMOVED***/static/vendor/modernize/libs/simplebar/simplebar.min.js
```

- [ ] **Step 3: Add .superpowers/ to .gitignore**

Open `.gitignore` and add at the bottom (if not already present):
```
.superpowers/
```

- [ ] **Step 4: Verify files exist**

```bash
ls ***REMOVED***/static/vendor/modernize/css/
ls ***REMOVED***/static/vendor/modernize/libs/preline/
ls ***REMOVED***/static/vendor/modernize/libs/simplebar/
```

Expected output: `theme.css`, `preline.js`, `simplebar.min.css`, `simplebar.min.js`

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/static/vendor/ .gitignore
git commit -m "chore: add Modernize theme.css and Preline/Simplebar static assets"
```

---

## Task 2: Create StaffRequiredMixin

**Files:**
- Create: `***REMOVED***/ui/mixins.py`
- Create: `***REMOVED***/ui/tests/__init__.py`
- Create: `***REMOVED***/ui/tests/test_views.py`

- [ ] **Step 1: Write the failing test**

Create `***REMOVED***/ui/tests/__init__.py` (empty), then create `***REMOVED***/ui/tests/test_views.py`:

```python
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from ***REMOVED***.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_dashboard_redirects_anonymous() -> None:
    client = Client()
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_dashboard_accessible_to_staff() -> None:
    user = UserFactory(is_staff=True)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 200
    assert b"ReelForge" in response.content


@pytest.mark.django_db
def test_dashboard_forbidden_to_non_staff() -> None:
    user = UserFactory(is_staff=False)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/test_views.py -v
```

Expected: FAIL (import errors — `DashboardView` doesn't exist yet as CBV)

- [ ] **Step 3: Create the mixin**

Create `***REMOVED***/ui/mixins.py`:

```python
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
```

- [ ] **Step 4: Commit mixin (tests still failing — that's expected at this stage)**

```bash
git add ***REMOVED***/ui/mixins.py ***REMOVED***/ui/tests/
git commit -m "feat(ui): add StaffRequiredMixin for CBV staff access control"
```

---

## Task 3: Rewrite base.html — Modernize Shell

**Files:**
- Rewrite: `***REMOVED***/ui/templates/ui/base.html`

- [ ] **Step 1: Rewrite base.html**

Replace the entire content of `***REMOVED***/ui/templates/ui/base.html`:

```html
{% load static %}
<!DOCTYPE html>
<html lang="en" dir="ltr" data-color-theme="Blue_Theme" class="dark selected"
  data-layout="vertical" data-boxed-layout="full" data-card="shadow">

<head>
  <meta charset="UTF-8" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}ReelForge{% endblock %}</title>

  <!-- Simplebar CSS -->
  <link rel="stylesheet" href="{% static 'vendor/modernize/libs/simplebar/simplebar.min.css' %}">
  <!-- Tabler Icons -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@2.44.0/tabler-icons.min.css">
  <!-- Plus Jakarta Sans -->
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <!-- Modernize theme CSS -->
  <link rel="stylesheet" href="{% static 'vendor/modernize/css/theme.css' %}" />

  <!-- HTMX -->
  <script defer src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"
          integrity="sha384-HGfztofotfshcF7+8n44JQL2oJmowVChPTg48S+jvZoztPfvwD79OC/LTtG6dMp+"
          crossorigin="anonymous"></script>
  <!-- Alpine.js -->
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js"></script>

  <script>
    document.addEventListener('htmx:configRequest', function(event) {
      event.detail.headers['X-CSRFToken'] = '{{ csrf_token }}';
    });
  </script>
  {% block extra_head %}{% endblock %}
</head>

<body class="bg-dark dark:bg-dark">
<main>
  <div id="main-wrapper" class="flex">

    <!-- ─── Left Sidebar ─── -->
    <aside id="application-sidebar-brand"
      class="hs-overlay hs-overlay-open:translate-x-0 -translate-x-full xl:translate-x-0
             fixed top-0 left-0 h-screen w-[270px] flex-shrink-0
             border-r border-border dark:border-darkborder
             bg-white dark:bg-dark
             transition-all duration-300 xl:z-[2] z-[60] hidden xl:block with-vertical left-sidebar">

      <!-- Brand -->
      <div class="py-5 px-5 flex items-center gap-2">
        <div class="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0">RF</div>
        <span class="text-lg font-bold text-dark dark:text-white hide-menu">ReelForge</span>
      </div>

      <!-- Scrollable nav -->
      <div class="overflow-hidden">
        <div class="scroll-sidebar" data-simplebar="">
          <div class="px-4 mt-4 mini-layout">
            <nav class="hs-accordion-group w-full flex flex-col">
              <ul id="sidebarnav">

                <!-- HOME -->
                <div class="caption">
                  <i class="ti ti-dots nav-small-cap-icon"></i>
                  <span class="hide-menu">Home</span>
                </div>
                <li class="sidebar-item">
                  <a class="sidebar-link dark-sidebar-link {% if nav_active == 'dashboard' %}active activemenu{% endif %}"
                     href="{% url 'ui:dashboard' %}">
                    <i class="ti ti-smart-home text-xl flex-shrink-0"></i>
                    <span class="hide-menu flex-shrink-0">Dashboard</span>
                  </a>
                </li>

                <!-- CLIPPING -->
                <div class="caption mt-4">
                  <i class="ti ti-dots nav-small-cap-icon"></i>
                  <span class="hide-menu">Clipping</span>
                </div>
                <li class="sidebar-item">
                  <a class="sidebar-link dark-sidebar-link {% if nav_active == 'clipping' %}active activemenu{% endif %}"
                     href="{% url 'clipping:job_list' %}">
                    <i class="ti ti-scissors text-xl flex-shrink-0"></i>
                    <span class="hide-menu flex-shrink-0">All Jobs</span>
                    {% if awaiting_approval_count %}
                    <span class="hide-menu ms-auto badge-md bg-warning text-white">{{ awaiting_approval_count }}</span>
                    {% endif %}
                  </a>
                </li>

                <!-- YOUTUBE -->
                <div class="caption mt-4">
                  <i class="ti ti-dots nav-small-cap-icon"></i>
                  <span class="hide-menu">YouTube</span>
                </div>
                <li class="sidebar-item">
                  <a class="sidebar-link dark-sidebar-link opacity-50 cursor-not-allowed" href="#">
                    <i class="ti ti-brand-youtube text-xl flex-shrink-0"></i>
                    <span class="hide-menu flex-shrink-0">Pipeline</span>
                    <span class="hide-menu ms-auto badge-sm bg-lightgray text-bodytext dark:bg-darkgray text-xs">soon</span>
                  </a>
                </li>

                <!-- CHANNELS -->
                <div class="caption mt-4">
                  <i class="ti ti-dots nav-small-cap-icon"></i>
                  <span class="hide-menu">Channels</span>
                </div>
                <li class="sidebar-item">
                  <a class="sidebar-link dark-sidebar-link opacity-50 cursor-not-allowed" href="#">
                    <i class="ti ti-tv text-xl flex-shrink-0"></i>
                    <span class="hide-menu flex-shrink-0">Channels</span>
                    <span class="hide-menu ms-auto badge-sm bg-lightgray text-bodytext dark:bg-darkgray text-xs">soon</span>
                  </a>
                </li>

              </ul>
            </nav>
          </div>
        </div>
      </div>
    </aside>
    <!-- ─── End Left Sidebar ─── -->

    <!-- ─── Page Wrapper ─── -->
    <div class="w-full page-wrapper xl:ps-[270px]">

      <!-- Top Header -->
      <header class="topbar sticky top-0 z-[1] bg-white dark:bg-dark border-b border-border dark:border-darkborder">
        <div class="flex items-center gap-4 px-6 py-3">
          <!-- Mobile sidebar toggle -->
          <a class="xl:hidden cursor-pointer text-xl text-link dark:text-darklink sidebartoggler"
             data-hs-overlay="#application-sidebar-brand"
             aria-controls="application-sidebar-brand"
             aria-label="Toggle navigation">
            <i class="ti ti-menu-2"></i>
          </a>
          <div class="flex-1"></div>
          <!-- User avatar -->
          <div class="w-9 h-9 rounded-full bg-primary flex items-center justify-center text-white text-sm font-bold cursor-default"
               title="{{ request.user.email }}">
            {{ request.user.email|first|upper }}
          </div>
        </div>
      </header>

      <!-- Main content -->
      <div class="py-6 px-6">
        <div class="page-container">
          {% block page_header %}{% endblock %}
          {% block content %}{% endblock %}
        </div>
      </div>

    </div>
    <!-- ─── End Page Wrapper ─── -->

  </div>
</main>

<!-- Simplebar JS -->
<script src="{% static 'vendor/modernize/libs/simplebar/simplebar.min.js' %}"></script>
<!-- Preline UI -->
<script src="{% static 'vendor/modernize/libs/preline/preline.js' %}"></script>

{% block extra_js %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: Verify base.html renders (Django check)**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run python manage.py check
```

Expected: `System check identified no issues`

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/ui/templates/ui/base.html
git commit -m "feat(ui): rewrite base.html with Modernize shell (dark sidebar + topbar)"
```

---

## Task 4: Rewrite status_badge.html with template badge classes

**Files:**
- Rewrite: `***REMOVED***/ui/templates/ui/partials/status_badge.html`

- [ ] **Step 1: Rewrite status_badge.html**

Replace entire content of `***REMOVED***/ui/templates/ui/partials/status_badge.html`:

```html
{% comment %}
Usage: {% include "ui/partials/status_badge.html" with status=job.status %}

Maps ClippingJob.Status / ClipRender.RenderStatus values to Modernize badge classes.
{% endcomment %}
{% if status == "RUNNING" or status == "INITIALIZING" or status == "DOWNLOADING" or status == "TRANSCRIBING" or status == "ANALYZING" or status == "DISTRIBUTING" %}
  <span class="badge-md bg-lightprimary text-primary dark:bg-darkprimary dark:text-primary">
    <i class="ti ti-loader-2 me-1 text-xs animate-spin"></i>{{ status|title }}
  </span>
{% elif status == "RENDERING" %}
  <span class="badge-md bg-lightsecondary text-secondary dark:bg-darksecondary dark:text-secondary">
    <i class="ti ti-video me-1 text-xs"></i>Rendering
  </span>
{% elif status == "AWAITING_CLIP_APPROVAL" %}
  <span class="badge-md bg-lightwarning text-warning dark:bg-darkwarning dark:text-warning">
    <i class="ti ti-clock me-1 text-xs"></i>Awaiting Approval
  </span>
{% elif status == "PAUSED_AT_GATE" or status == "PAUSED" %}
  <span class="badge-md bg-lightwarning text-warning dark:bg-darkwarning dark:text-warning">
    <i class="ti ti-player-pause me-1 text-xs"></i>Paused
  </span>
{% elif status == "COMPLETED" or status == "RENDERED" or status == "DISTRIBUTED" %}
  <span class="badge-md bg-lightsuccess text-success dark:bg-darksuccess dark:text-success">
    <i class="ti ti-circle-check me-1 text-xs"></i>{{ status|title }}
  </span>
{% elif status == "FAILED" %}
  <span class="badge-md bg-lighterror text-error dark:bg-darkerror dark:text-error">
    <i class="ti ti-circle-x me-1 text-xs"></i>Failed
  </span>
{% elif status == "PROPOSED" %}
  <span class="badge-md bg-lightinfo text-info dark:bg-darkinfo dark:text-info">
    Proposed
  </span>
{% elif status == "APPROVED" %}
  <span class="badge-md bg-lightsuccess text-success dark:bg-darksuccess dark:text-success">
    <i class="ti ti-check me-1 text-xs"></i>Approved
  </span>
{% elif status == "REJECTED" %}
  <span class="badge-md bg-lighterror text-error dark:bg-darkerror dark:text-error">
    Rejected
  </span>
{% else %}
  <span class="badge-md bg-lightgray text-bodytext dark:bg-darkgray">{{ status|title }}</span>
{% endif %}
```

- [ ] **Step 2: Commit**

```bash
git add ***REMOVED***/ui/templates/ui/partials/status_badge.html
git commit -m "feat(ui): rewrite status_badge partial with Modernize badge-md classes"
```

---

## Task 5: Convert ui/views.py to CBVs + rewrite dashboard templates

**Files:**
- Rewrite: `***REMOVED***/ui/views.py`
- Rewrite: `***REMOVED***/ui/urls.py`
- Rewrite: `***REMOVED***/ui/templates/ui/dashboard.html`
- Rewrite: `***REMOVED***/ui/templates/ui/partials/active_jobs.html`

- [ ] **Step 1: Rewrite ui/views.py with CBVs**

Replace entire content of `***REMOVED***/ui/views.py`:

```python
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from django.views.generic import TemplateView

from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.ui.mixins import StaffRequiredMixin

_ACTIVE_STATUSES = [
    ClippingJob.Status.INITIALIZING,
    ClippingJob.Status.DOWNLOADING,
    ClippingJob.Status.TRANSCRIBING,
    ClippingJob.Status.ANALYZING,
    ClippingJob.Status.AWAITING_CLIP_APPROVAL,
    ClippingJob.Status.RENDERING,
    ClippingJob.Status.DISTRIBUTING,
]


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "ui/dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        active_jobs = (
            ClippingJob.objects.filter(status__in=_ACTIVE_STATUSES)
            .select_related("channel")
            .order_by("-created_at")[:20]
        )
        awaiting_approval = (
            ClippingJob.objects.filter(status=ClippingJob.Status.AWAITING_CLIP_APPROVAL)
            .select_related("channel")
            .annotate(candidate_count=Count("candidates"))
            .order_by("-updated_at")
        )
        context.update({
            "active_jobs": active_jobs,
            "awaiting_approval": awaiting_approval,
            "active_jobs_count": active_jobs.count(),
            "awaiting_approval_count": awaiting_approval.count(),
            "completed_today_count": ClippingJob.objects.filter(
                status=ClippingJob.Status.COMPLETED,
                completed_at__date=today,
            ).count(),
            "nav_active": "dashboard",
        })
        return context


class ActiveJobsPartialView(StaffRequiredMixin, TemplateView):
    """HTMX partial — polled every 2s to refresh the active jobs table."""
    template_name = "ui/partials/active_jobs.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["active_jobs"] = (
            ClippingJob.objects.filter(status__in=_ACTIVE_STATUSES)
            .select_related("channel")
            .order_by("-created_at")[:20]
        )
        return context
```

- [ ] **Step 2: Rewrite ui/urls.py**

Replace entire content of `***REMOVED***/ui/urls.py`:

```python
from __future__ import annotations

from django.urls import path

from ***REMOVED***.ui.views import ActiveJobsPartialView
from ***REMOVED***.ui.views import DashboardView

app_name = "ui"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("partials/active-jobs/", ActiveJobsPartialView.as_view(), name="active_jobs_partial"),
]
```

- [ ] **Step 3: Rewrite dashboard.html**

Replace entire content of `***REMOVED***/ui/templates/ui/dashboard.html`:

```html
{% extends "ui/base.html" %}
{% load static %}

{% block page_header %}
<div class="flex items-center justify-between mb-6">
  <div>
    <h5 class="card-title text-xl">Dashboard</h5>
    <p class="card-subtitle">{{ request.user.email }}</p>
  </div>
</div>
{% endblock %}

{% block content %}

<!-- Stats row -->
<div class="grid grid-cols-12 gap-6 mb-6">
  <div class="col-span-12 sm:col-span-6 lg:col-span-3">
    <div class="card shadow-none bg-lightprimary dark:bg-darkprimary">
      <div class="card-body">
        <div class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-full bg-primary flex items-center justify-center flex-shrink-0">
            <i class="ti ti-activity text-2xl text-white"></i>
          </div>
          <div>
            <p class="text-primary font-semibold text-sm mb-0">Active Jobs</p>
            <h5 class="text-2xl font-bold text-primary mb-0">{{ active_jobs_count }}</h5>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-span-12 sm:col-span-6 lg:col-span-3">
    <div class="card shadow-none bg-lightwarning dark:bg-darkwarning">
      <div class="card-body">
        <div class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-full bg-warning flex items-center justify-center flex-shrink-0">
            <i class="ti ti-clock text-2xl text-white"></i>
          </div>
          <div>
            <p class="text-warning font-semibold text-sm mb-0">Awaiting Approval</p>
            <h5 class="text-2xl font-bold text-warning mb-0">{{ awaiting_approval_count }}</h5>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-span-12 sm:col-span-6 lg:col-span-3">
    <div class="card shadow-none bg-lightsuccess dark:bg-darksuccess">
      <div class="card-body">
        <div class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-full bg-success flex items-center justify-center flex-shrink-0">
            <i class="ti ti-circle-check text-2xl text-white"></i>
          </div>
          <div>
            <p class="text-success font-semibold text-sm mb-0">Completed Today</p>
            <h5 class="text-2xl font-bold text-success mb-0">{{ completed_today_count }}</h5>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-span-12 sm:col-span-6 lg:col-span-3">
    <div class="card shadow-none bg-lightinfo dark:bg-darkinfo">
      <div class="card-body">
        <div class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-full bg-info flex items-center justify-center flex-shrink-0">
            <i class="ti ti-hourglass text-2xl text-white"></i>
          </div>
          <div>
            <p class="text-info font-semibold text-sm mb-0">Approval Queue</p>
            <h5 class="text-2xl font-bold text-info mb-0">{{ awaiting_approval|length }}</h5>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Two column: active jobs + needs attention -->
<div class="grid grid-cols-12 gap-6">

  <!-- Active jobs (HTMX polled) -->
  <div class="col-span-12 lg:col-span-8">
    <div class="card">
      <div class="card-body pb-0">
        <div class="flex items-center justify-between mb-4">
          <h5 class="card-title mb-0">Active Jobs</h5>
          <span class="text-sm text-bodytext dark:text-darklink">Auto-refreshes every 2s</span>
        </div>
      </div>
      <div id="active-jobs-table"
           hx-get="{% url 'ui:active_jobs_partial' %}"
           hx-trigger="every 2s"
           hx-swap="innerHTML">
        {% include "ui/partials/active_jobs.html" %}
      </div>
    </div>
  </div>

  <!-- Needs attention -->
  <div class="col-span-12 lg:col-span-4">
    <div class="card border-warning">
      <div class="card-body">
        <h5 class="card-title text-warning mb-4">
          <i class="ti ti-alert-triangle me-2"></i>Needs Attention
        </h5>
        {% if awaiting_approval %}
          <div class="-m-1.5 overflow-x-auto">
            <div class="p-1.5 min-w-full inline-block align-middle">
              <div class="divide-y divide-border dark:divide-darkborder">
                {% for job in awaiting_approval %}
                <a href="{% url 'clipping:job_detail' job.id %}"
                   class="flex items-center gap-3 py-3 hover:bg-lightgray dark:hover:bg-darkgray px-2 rounded-md transition-colors">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-dark dark:text-white truncate mb-0">
                      {{ job.source_title|default:"Untitled"|truncatechars:40 }}
                    </p>
                    <p class="text-xs text-bodytext dark:text-darklink mb-0">{{ job.channel.name }}</p>
                  </div>
                  <span class="badge-md bg-lightwarning text-warning dark:bg-darkwarning dark:text-warning flex-shrink-0">
                    {{ job.candidate_count }} clips
                  </span>
                </a>
                {% endfor %}
              </div>
            </div>
          </div>
        {% else %}
          <p class="text-sm text-bodytext dark:text-darklink text-center py-4">Nothing needs attention.</p>
        {% endif %}
      </div>
    </div>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 4: Rewrite active_jobs.html partial**

Replace entire content of `***REMOVED***/ui/templates/ui/partials/active_jobs.html`:

```html
{% if active_jobs %}
<div class="-m-1.5 overflow-x-auto">
  <div class="p-1.5 min-w-full inline-block align-middle">
    <table class="min-w-full divide-y divide-border dark:divide-darkborder">
      <thead>
        <tr>
          <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Title</th>
          <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Channel</th>
          <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Status</th>
          <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Started</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-border dark:divide-darkborder">
        {% for job in active_jobs %}
        <tr class="hover:bg-lightgray dark:hover:bg-darkgray cursor-pointer"
            onclick="window.location='{% url 'clipping:job_detail' job.id %}'">
          <td class="p-4 whitespace-nowrap">
            <p class="text-sm font-medium text-dark dark:text-white mb-0 truncate max-w-xs">
              {{ job.source_title|default:"Untitled" }}
            </p>
          </td>
          <td class="p-4 whitespace-nowrap">
            <p class="text-sm text-bodytext dark:text-darklink mb-0">{{ job.channel.name }}</p>
          </td>
          <td class="p-4 whitespace-nowrap">
            {% include "ui/partials/status_badge.html" with status=job.status %}
          </td>
          <td class="p-4 whitespace-nowrap">
            <p class="text-sm text-bodytext dark:text-darklink mb-0">{{ job.created_at|timesince }} ago</p>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% else %}
<div class="p-8 text-center">
  <p class="text-sm text-bodytext dark:text-darklink">No active jobs.</p>
</div>
{% endif %}
```

- [ ] **Step 5: Run tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/test_views.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/ui/views.py ***REMOVED***/ui/urls.py \
        ***REMOVED***/ui/templates/ui/dashboard.html \
        ***REMOVED***/ui/templates/ui/partials/active_jobs.html
git commit -m "feat(ui): convert dashboard views to CBVs + rewrite dashboard templates"
```

---

## Task 6: Convert clipping/views/jobs.py to CBVs + rewrite job_list.html

**Files:**
- Rewrite: `***REMOVED***/clipping/views/jobs.py`
- Rewrite: `***REMOVED***/clipping/templates/clipping/job_list.html`

- [ ] **Step 1: Write failing tests**

Add to `***REMOVED***/ui/tests/test_views.py`:

```python
from ***REMOVED***.clipping.tests.factories import ClippingJobFactory


@pytest.mark.django_db
def test_clipping_job_list_accessible_to_staff() -> None:
    user = UserFactory(is_staff=True)
    ClippingJobFactory()
    client = Client()
    client.force_login(user)
    response = client.get(reverse("clipping:job_list"))
    assert response.status_code == 200
    assert b"Clipping Jobs" in response.content


@pytest.mark.django_db
def test_clipping_job_list_filters_by_status() -> None:
    user = UserFactory(is_staff=True)
    from ***REMOVED***.clipping.models import ClippingJob
    ClippingJobFactory(status=ClippingJob.Status.COMPLETED)
    ClippingJobFactory(status=ClippingJob.Status.ANALYZING)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("clipping:job_list") + "?status=COMPLETED")
    assert response.status_code == 200
```

Run to verify fail:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/test_views.py::test_clipping_job_list_accessible_to_staff -v
```

Expected: FAIL (import error for `ClippingJobFactory` — add that to the import at the top once confirmed failing)

- [ ] **Step 2: Rewrite clipping/views/jobs.py with CBVs**

Replace entire content of `***REMOVED***/clipping/views/jobs.py`:

```python
from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.ui.mixins import StaffRequiredMixin

_FSM_STAGE_ORDER = [
    ClippingJob.Status.INITIALIZING,
    ClippingJob.Status.DOWNLOADING,
    ClippingJob.Status.TRANSCRIBING,
    ClippingJob.Status.ANALYZING,
    ClippingJob.Status.AWAITING_CLIP_APPROVAL,
    ClippingJob.Status.RENDERING,
    ClippingJob.Status.DISTRIBUTING,
    ClippingJob.Status.COMPLETED,
]

_FSM_STAGE_LABELS = [
    (ClippingJob.Status.INITIALIZING, "Init"),
    (ClippingJob.Status.DOWNLOADING, "Download"),
    (ClippingJob.Status.TRANSCRIBING, "Transcribe"),
    (ClippingJob.Status.ANALYZING, "Analyze"),
    (ClippingJob.Status.AWAITING_CLIP_APPROVAL, "Approval"),
    (ClippingJob.Status.RENDERING, "Render"),
    (ClippingJob.Status.DISTRIBUTING, "Distribute"),
    (ClippingJob.Status.COMPLETED, "Done"),
]


def _get_completed_stages(job: ClippingJob) -> set[str]:
    """Return set of stage status values that precede the current status."""
    try:
        current_idx = _FSM_STAGE_ORDER.index(job.status)
    except ValueError:
        current_idx = 0
    return {s.value for s in _FSM_STAGE_ORDER[:current_idx]}


class JobListView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/job_list.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get("status", "")
        jobs = ClippingJob.objects.select_related("channel").order_by("-created_at")
        if status_filter:
            jobs = jobs.filter(status=status_filter)
        context.update({
            "jobs": jobs,
            "status_filter": status_filter,
            "status_choices": ClippingJob.Status.choices,
            "nav_active": "clipping",
        })
        return context


class JobDetailView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/job_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        job = get_object_or_404(
            ClippingJob.objects.select_related("channel").prefetch_related(
                "candidates__layout_config",
                "candidates__style_config",
            ),
            id=self.kwargs["job_id"],
        )
        context.update({
            "job": job,
            "candidates": job.candidates.order_by("-relevance_score"),
            "nav_active": "clipping",
            "fsm_stages": _FSM_STAGE_LABELS,
            "job_completed_stages": _get_completed_stages(job),
        })
        return context


class JobStatusPartialView(StaffRequiredMixin, TemplateView):
    """HTMX partial — returns just the stage tracker strip."""
    template_name = "clipping/partials/job_status.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        job = get_object_or_404(ClippingJob, id=self.kwargs["job_id"])
        context.update({
            "job": job,
            "fsm_stages": _FSM_STAGE_LABELS,
            "job_completed_stages": _get_completed_stages(job),
            "terminal": job.status in (ClippingJob.Status.COMPLETED, ClippingJob.Status.FAILED),
        })
        return context
```

- [ ] **Step 3: Rewrite clipping/job_list.html**

Replace entire content of `***REMOVED***/clipping/templates/clipping/job_list.html`:

```html
{% extends "ui/base.html" %}

{% block page_header %}
<div class="flex items-center justify-between mb-6">
  <div>
    <h5 class="card-title text-xl">Clipping Jobs</h5>
    <p class="card-subtitle">All video clipping jobs across channels</p>
  </div>
</div>
{% endblock %}

{% block content %}

<!-- Status filter tabs -->
<div class="flex gap-2 mb-6 flex-wrap">
  <a href="{% url 'clipping:job_list' %}"
     class="btn btn-sm {% if not status_filter %}btn-primary{% else %}btn-outline-primary{% endif %}">
    All
  </a>
  {% for value, label in status_choices %}
  <a href="?status={{ value }}"
     class="btn btn-sm {% if status_filter == value %}btn-primary{% else %}btn-outline-primary{% endif %}">
    {{ label }}
  </a>
  {% endfor %}
</div>

<!-- Jobs table -->
<div class="card">
  <div class="card-body p-0">
    <div class="-m-1.5 overflow-x-auto">
      <div class="p-1.5 min-w-full inline-block align-middle">
        {% if jobs %}
        <div class="border overflow-hidden border-light-dark rounded-md">
          <table class="min-w-full divide-y divide-border dark:divide-darkborder">
            <thead>
              <tr>
                <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Title</th>
                <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Channel</th>
                <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Status</th>
                <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Clips</th>
                <th class="p-4 text-start text-sm font-semibold text-dark dark:text-white capitalize">Created</th>
                <th class="p-4"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border dark:divide-darkborder">
              {% for job in jobs %}
              <tr class="hover:bg-lightgray dark:hover:bg-darkgray cursor-pointer"
                  onclick="window.location='{% url 'clipping:job_detail' job.id %}'">
                <td class="p-4 whitespace-nowrap">
                  <p class="text-sm font-semibold text-dark dark:text-white mb-0">
                    {{ job.source_title|default:"Untitled" }}
                  </p>
                  {% if job.source_url %}
                  <p class="text-xs text-bodytext dark:text-darklink mb-0 truncate max-w-xs">
                    {{ job.source_url|truncatechars:50 }}
                  </p>
                  {% endif %}
                </td>
                <td class="p-4 whitespace-nowrap">
                  <p class="text-sm text-bodytext dark:text-darklink mb-0">{{ job.channel.name }}</p>
                </td>
                <td class="p-4 whitespace-nowrap">
                  {% include "ui/partials/status_badge.html" with status=job.status %}
                </td>
                <td class="p-4 whitespace-nowrap">
                  {% with count=job.candidates.count %}
                  {% if count %}
                  <span class="text-sm font-semibold text-dark dark:text-white">{{ count }}</span>
                  {% else %}
                  <span class="text-sm text-bodytext dark:text-darklink">—</span>
                  {% endif %}
                  {% endwith %}
                </td>
                <td class="p-4 whitespace-nowrap">
                  <p class="text-sm text-bodytext dark:text-darklink mb-0">{{ job.created_at|date:"M d, Y" }}</p>
                </td>
                <td class="p-4 whitespace-nowrap text-end">
                  <a href="{% url 'clipping:job_detail' job.id %}"
                     class="h-8 w-8 inline-flex items-center justify-center rounded-full hover:bg-lightprimary hover:text-primary dark:hover:bg-darkprimary transition-colors"
                     onclick="event.stopPropagation()">
                    <i class="ti ti-chevron-right text-lg"></i>
                  </a>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% else %}
        <div class="text-center py-12">
          <i class="ti ti-video-off text-4xl text-bodytext dark:text-darklink mb-3 block"></i>
          <p class="text-sm text-bodytext dark:text-darklink">No jobs found.</p>
        </div>
        {% endif %}
      </div>
    </div>
  </div>
</div>

{% endblock %}
```

- [ ] **Step 4: Run tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/test_views.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/views/jobs.py \
        ***REMOVED***/clipping/templates/clipping/job_list.html \
        ***REMOVED***/ui/tests/test_views.py
git commit -m "feat(clipping): convert job views to CBVs + rewrite job list with Modernize table"
```

---

## Task 7: Rewrite job_detail.html with Modernize styling

**Files:**
- Rewrite: `***REMOVED***/clipping/templates/clipping/job_detail.html`

- [ ] **Step 1: Rewrite job_detail.html**

Replace entire content of `***REMOVED***/clipping/templates/clipping/job_detail.html`:

```html
{% extends "ui/base.html" %}
{% load static %}

{% block page_header %}
<!-- Breadcrumb -->
<nav class="flex items-center gap-2 text-sm text-bodytext dark:text-darklink mb-4">
  <a href="{% url 'clipping:job_list' %}" class="hover:text-primary transition-colors">Clipping</a>
  <i class="ti ti-chevron-right text-xs"></i>
  <span class="text-dark dark:text-white">{{ job.source_title|default:"Untitled"|truncatechars:60 }}</span>
</nav>

<div class="flex items-start justify-between mb-6">
  <div>
    <h5 class="card-title text-xl mb-1">{{ job.source_title|default:"Untitled" }}</h5>
    <div class="flex items-center gap-3 flex-wrap">
      {% if job.source_url %}
        <a href="{{ job.source_url }}" target="_blank"
           class="text-sm text-primary hover:underline truncate max-w-xs">
          {{ job.source_url|truncatechars:50 }}
        </a>
        <span class="text-bodytext">·</span>
      {% endif %}
      <span class="text-sm text-bodytext dark:text-darklink">{{ job.channel.name }}</span>
      {% if job.source_duration_sec %}
        <span class="text-bodytext">·</span>
        <span class="text-sm text-bodytext dark:text-darklink">{{ job.source_duration_sec|floatformat:0 }}s source</span>
      {% endif %}
    </div>
  </div>
  {% include "ui/partials/status_badge.html" with status=job.status %}
</div>
{% endblock %}

{% block content %}

<!-- Pipeline Stage Tracker -->
<div class="card mb-6">
  <div class="card-body">
    {% include "clipping/partials/job_status.html" %}
  </div>
</div>

<!-- Clip Candidates -->
{% if job.status == 'AWAITING_CLIP_APPROVAL' or job.status == 'RENDERING' or job.status == 'DISTRIBUTING' or job.status == 'COMPLETED' %}
<div class="card">
  <div class="card-body">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h5 class="card-title mb-0">
          Clip Candidates
          <span class="text-bodytext dark:text-darklink font-normal text-base ms-2">{{ candidates|length }} found</span>
        </h5>
        {% if job.status == 'AWAITING_CLIP_APPROVAL' %}
          <p class="card-subtitle mt-1">Approve clips to include in the render. Rejected clips are skipped.</p>
        {% endif %}
      </div>
      {% if job.status == 'AWAITING_CLIP_APPROVAL' %}
      <div class="flex gap-3">
        <button hx-post="{% url 'clipping:job_approve_all' job.id %}"
                hx-target="#candidates-list"
                hx-swap="innerHTML"
                class="btn btn-outline-primary btn-sm">
          Approve All
        </button>
        <button hx-post="{% url 'clipping:job_start_render' job.id %}"
                hx-confirm="Start rendering all approved clips?"
                class="btn btn-primary btn-sm">
          Render Approved <i class="ti ti-arrow-right ms-1"></i>
        </button>
      </div>
      {% endif %}
    </div>

    <div id="candidates-list" class="-mx-5">
      {% for candidate in candidates %}
        {% include "clipping/partials/candidate_row.html" with candidate=candidate job=job %}
      {% empty %}
        <div class="text-center py-8">
          <p class="text-sm text-bodytext dark:text-darklink">No clip candidates found.</p>
        </div>
      {% endfor %}
    </div>

  </div>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 2: Verify page loads**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run python manage.py check
```

Expected: `System check identified no issues`

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/templates/clipping/job_detail.html
git commit -m "feat(clipping): rewrite job detail template with Modernize card styling"
```

---

## Task 8: Convert clipping/views/candidates.py to CBVs

**Files:**
- Rewrite: `***REMOVED***/clipping/views/candidates.py`

- [ ] **Step 1: Write failing test**

Add to `***REMOVED***/ui/tests/test_views.py`:

```python
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory


@pytest.mark.django_db
def test_candidate_detail_accessible_to_staff() -> None:
    user = UserFactory(is_staff=True)
    candidate = ClipCandidateFactory()
    client = Client()
    client.force_login(user)
    response = client.get(reverse("clipping:candidate_detail", kwargs={"candidate_id": candidate.pk}))
    assert response.status_code == 200
```

Run to verify fail:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/test_views.py::test_candidate_detail_accessible_to_staff -v
```

Expected: FAIL (import path issues — this will verify the test machinery works before the refactor)

- [ ] **Step 2: Rewrite clipping/views/candidates.py with CBVs**

Replace entire content of `***REMOVED***/clipping/views/candidates.py`:

```python
from __future__ import annotations

import logging

from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipRenderMode
from ***REMOVED***.clipping.models import ClipRenderStyleMixin
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay
from ***REMOVED***.clipping.tasks import preview_clip_layout
from ***REMOVED***.clipping.tasks import render_clip
from ***REMOVED***.ui.mixins import StaffRequiredMixin

_BOOLEAN_STYLE_FIELDS = frozenset({
    "caption_enabled",
    "hook_enabled",
    "watermark_enabled",
    "progress_bar_enabled",
    "music_enabled",
})

_INT_STYLE_FIELDS = frozenset({
    "caption_size",
    "caption_stroke_width",
    "watermark_size",
    "progress_bar_height",
    "hook_size",
})

_FLOAT_STYLE_FIELDS = frozenset({
    "hook_duration_sec",
    "transition_duration_sec",
    "watermark_opacity",
    "music_volume_db",
    "music_fade_in_sec",
    "music_fade_out_sec",
})

_STYLE_FIELD_SET = frozenset(ClipRenderStyleMixin.STYLE_FIELD_NAMES)

logger = logging.getLogger("***REMOVED***.clipping")


class CandidateApproveView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
        )
        candidate.approved = True
        candidate.status = ClipCandidate.CandidateStatus.APPROVED
        candidate.approved_by = request.user
        candidate.approved_at = timezone.now()
        candidate.save(
            update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"]
        )
        logger.info(
            "Clip candidate approved",
            extra={"candidate_id": str(candidate_id), "user": request.user.email},
        )
        return self.render_candidate_row(request, candidate)

    @staticmethod
    def render_candidate_row(request: HttpRequest, candidate: ClipCandidate) -> HttpResponse:
        return HttpResponse(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": candidate, "job": candidate.clipping_job},
                request=request,
            )
        )


class CandidateRejectView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
        )
        candidate.approved = False
        candidate.status = ClipCandidate.CandidateStatus.REJECTED
        candidate.save(update_fields=["approved", "status", "updated_at"])
        logger.info(
            "Clip candidate rejected",
            extra={"candidate_id": str(candidate_id), "user": request.user.email},
        )
        return HttpResponse(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": candidate, "job": candidate.clipping_job},
                request=request,
            )
        )


class CandidateUndoRejectView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
        )
        candidate.approved = None
        candidate.status = ClipCandidate.CandidateStatus.PROPOSED
        candidate.save(update_fields=["approved", "status", "updated_at"])
        return HttpResponse(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": candidate, "job": candidate.clipping_job},
                request=request,
            )
        )


class JobApproveAllView(StaffRequiredMixin, View):
    """Approve all PROPOSED candidates for a job. Returns the full candidates list HTML."""
    def post(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(ClippingJob, id=job_id)
        now = timezone.now()
        proposed = list(job.candidates.filter(status=ClipCandidate.CandidateStatus.PROPOSED))
        for candidate in proposed:
            candidate.approved = True
            candidate.status = ClipCandidate.CandidateStatus.APPROVED
            candidate.approved_by = request.user
            candidate.approved_at = now
            candidate.save(
                update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"]
            )
        all_candidates = job.candidates.order_by("-relevance_score")
        logger.info(
            "Approved all candidates for job",
            extra={"job_id": str(job_id), "count": len(proposed), "user": request.user.email},
        )
        html = "".join(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": c, "job": job},
                request=request,
            )
            for c in all_candidates
        )
        return HttpResponse(html)


class JobStartRenderView(StaffRequiredMixin, View):
    """Trigger render_clip task for all APPROVED candidates."""
    def post(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(ClippingJob, id=job_id)
        approved_candidates = list(
            job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED)
        )
        triggered = 0
        for candidate in approved_candidates:
            render_clip.delay(str(candidate.id))
            candidate.status = ClipCandidate.CandidateStatus.RENDERING
            candidate.save(update_fields=["status", "updated_at"])
            triggered += 1

        if triggered > 0 and can_proceed(job.begin_rendering):
            try:
                job.begin_rendering()
                job.save(update_fields=["status", "updated_at"])
            except TransitionNotAllowed:
                logger.warning(
                    "Cannot transition job to RENDERING",
                    extra={"job_id": str(job_id), "current_status": job.status},
                )

        logger.info(
            "Started render for approved candidates",
            extra={"job_id": str(job_id), "triggered": triggered, "user": request.user.email},
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/app/clipping/{job_id}/"
        return response


class CandidateDetailView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/candidate_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel")
            .prefetch_related("timed_overlays"),
            pk=self.kwargs["candidate_id"],
        )
        context.update({
            "candidate": candidate,
            "job": candidate.clipping_job,
            "layout": getattr(candidate, "layout_config", None),
            "style": getattr(candidate, "style_config", None),
            "renders": candidate.renders.prefetch_related("stage_results").order_by("-created_at"),
            "timed_overlays": list(candidate.timed_overlays.all()),
            "nav_active": "clipping",
        })
        return context


class UpdateLayoutConfigView(StaffRequiredMixin, View):
    """Save render_mode and/or render_format; return the swapped layout editor partial."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout, _ = ClipLayoutConfig.objects.get_or_create(candidate=candidate)
        update_fields: list[str] = ["updated_at"]
        if "render_mode" in request.POST:
            layout.render_mode = request.POST["render_mode"]
            update_fields.append("render_mode")
        if "render_format" in request.POST:
            layout.render_format = request.POST["render_format"]
            update_fields.append("render_format")
        layout.save(update_fields=update_fields)
        return HttpResponse(
            render_to_string(
                "clipping/partials/layout_editor.html",
                {"candidate": candidate, "layout": layout},
                request=request,
            )
        )


class UpdateLayoutRegionsView(StaffRequiredMixin, View):
    """Save drag-editor coordinate fields. Returns 200 with no body (hx-swap='none')."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout, _ = ClipLayoutConfig.objects.get_or_create(candidate=candidate)
        coord_fields = [
            "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h",
            "region_a_x", "region_a_y", "region_a_w", "region_a_h",
            "region_b_x", "region_b_y", "region_b_w", "region_b_h",
        ]
        update_fields: list[str] = ["updated_at"]
        for field in coord_fields:
            if field in request.POST and request.POST[field] != "":
                try:
                    setattr(layout, field, int(request.POST[field]))
                    update_fields.append(field)
                except (ValueError, TypeError):
                    pass
        if "stack_ratio" in request.POST:
            try:
                val = float(request.POST["stack_ratio"])
                if 0.3 <= val <= 0.8:
                    layout.stack_ratio = val
                    update_fields.append("stack_ratio")
            except (ValueError, TypeError):
                pass
        layout.save(update_fields=update_fields)
        return HttpResponse(status=200)


class ResetSmartCropView(StaffRequiredMixin, View):
    """Clear manual Smart Crop coordinates; return refreshed layout editor partial."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
        layout.manual_crop_x = None
        layout.manual_crop_y = None
        layout.manual_crop_w = None
        layout.manual_crop_h = None
        layout.save(update_fields=[
            "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at",
        ])
        return HttpResponse(
            render_to_string(
                "clipping/partials/layout_editor.html",
                {"candidate": candidate, "layout": layout},
                request=request,
            )
        )


class UpdateStyleConfigView(StaffRequiredMixin, View):
    """Save any style config fields sent in POST."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        style, _ = ClipStyleConfig.objects.get_or_create(candidate=candidate)
        update_fields: list[str] = ["updated_at"]
        for field_name in _STYLE_FIELD_SET - {"emoji_keyword_map"}:
            if field_name in _BOOLEAN_STYLE_FIELDS:
                val = field_name in request.POST
                setattr(style, field_name, val)
                update_fields.append(field_name)
            elif field_name in request.POST:
                raw = request.POST[field_name]
                try:
                    if field_name in _INT_STYLE_FIELDS:
                        setattr(style, field_name, int(raw))
                    elif field_name in _FLOAT_STYLE_FIELDS:
                        setattr(style, field_name, float(raw))
                    else:
                        setattr(style, field_name, raw)
                    update_fields.append(field_name)
                except (ValueError, TypeError):
                    pass
        style.save(update_fields=update_fields)
        return HttpResponse(status=200)


class TriggerPreviewView(StaffRequiredMixin, View):
    """Fire the preview_clip_layout Celery task. Returns the polling preview panel."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
        preview_clip_layout.delay(str(layout.pk))
        return HttpResponse(
            render_to_string(
                "clipping/partials/preview_panel.html",
                {"candidate": candidate, "layout": layout, "polling": True},
                request=request,
            )
        )


class PreviewStatusView(StaffRequiredMixin, View):
    """HTMX polling endpoint: returns preview panel partial."""
    def get(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout = getattr(candidate, "layout_config", None)
        is_ready = layout is not None and bool(layout.preview_image)
        return HttpResponse(
            render_to_string(
                "clipping/partials/preview_panel.html",
                {"candidate": candidate, "layout": layout, "polling": not is_ready},
                request=request,
            )
        )


class AddOverlayView(StaffRequiredMixin, View):
    """Create a new timed overlay with defaults; return the new overlay row partial."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        overlay = ClipTimedOverlay.objects.create(
            candidate=candidate,
            text="New overlay",
            start_sec=0.0,
            end_sec=5.0,
        )
        return HttpResponse(
            render_to_string(
                "clipping/partials/overlay_row.html",
                {"overlay": overlay, "candidate": candidate},
                request=request,
            )
        )


class UpdateOverlayView(StaffRequiredMixin, View):
    """Save text/time fields for a timed overlay."""
    def post(self, request: HttpRequest, overlay_id: str) -> HttpResponse:
        overlay = get_object_or_404(ClipTimedOverlay, pk=overlay_id)
        update_fields: list[str] = ["updated_at"]
        if "text" in request.POST:
            overlay.text = request.POST["text"]
            update_fields.append("text")
        for field in ("start_sec", "end_sec", "position_x", "position_y", "font_size"):
            if field in request.POST:
                try:
                    val: float | int = (
                        float(request.POST[field]) if "sec" in field else int(request.POST[field])
                    )
                    setattr(overlay, field, val)
                    update_fields.append(field)
                except (ValueError, TypeError):
                    pass
        overlay.save(update_fields=update_fields)
        return HttpResponse(status=200)


class DeleteOverlayView(StaffRequiredMixin, View):
    """Delete a timed overlay; return empty 200 (HTMX outerHTML swap removes the row)."""
    def post(self, request: HttpRequest, overlay_id: str) -> HttpResponse:
        overlay = get_object_or_404(ClipTimedOverlay, pk=overlay_id)
        overlay.delete()
        return HttpResponse(status=200)


class UpdateRenderGatesView(StaffRequiredMixin, View):
    """Save the render_gates list for a candidate."""
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        raw_gates = request.POST.get("gates", "").strip()
        gates: list[int] = []
        if raw_gates:
            for part in raw_gates.split(","):
                try:
                    val = int(part.strip())
                    if 1 <= val <= 10:
                        gates.append(val)
                except (ValueError, TypeError):
                    pass
        candidate.render_gates = sorted(set(gates))
        candidate.save(update_fields=["render_gates", "updated_at"])
        return HttpResponse(
            render_to_string(
                "clipping/partials/gates_panel.html",
                {"candidate": candidate},
                request=request,
            )
        )
```

- [ ] **Step 3: Update clipping/urls.py to use CBVs**

Replace entire content of `***REMOVED***/clipping/urls.py`:

```python
from __future__ import annotations

from django.urls import path

from ***REMOVED***.clipping.views.candidates import AddOverlayView
from ***REMOVED***.clipping.views.candidates import CandidateApproveView
from ***REMOVED***.clipping.views.candidates import CandidateDetailView
from ***REMOVED***.clipping.views.candidates import CandidateRejectView
from ***REMOVED***.clipping.views.candidates import CandidateUndoRejectView
from ***REMOVED***.clipping.views.candidates import DeleteOverlayView
from ***REMOVED***.clipping.views.candidates import JobApproveAllView
from ***REMOVED***.clipping.views.candidates import JobStartRenderView
from ***REMOVED***.clipping.views.candidates import PreviewStatusView
from ***REMOVED***.clipping.views.candidates import ResetSmartCropView
from ***REMOVED***.clipping.views.candidates import TriggerPreviewView
from ***REMOVED***.clipping.views.candidates import UpdateLayoutConfigView
from ***REMOVED***.clipping.views.candidates import UpdateLayoutRegionsView
from ***REMOVED***.clipping.views.candidates import UpdateOverlayView
from ***REMOVED***.clipping.views.candidates import UpdateRenderGatesView
from ***REMOVED***.clipping.views.candidates import UpdateStyleConfigView
from ***REMOVED***.clipping.views.jobs import JobDetailView
from ***REMOVED***.clipping.views.jobs import JobListView
from ***REMOVED***.clipping.views.jobs import JobStatusPartialView
from ***REMOVED***.clipping.views.renders import RenderDetailView
from ***REMOVED***.clipping.views.renders import RerunFromStageView
from ***REMOVED***.clipping.views.renders import ResumeRenderView
from ***REMOVED***.clipping.views.renders import StageListPartialView

app_name = "clipping"

urlpatterns = [
    # Job views
    path("", JobListView.as_view(), name="job_list"),
    path("<uuid:job_id>/", JobDetailView.as_view(), name="job_detail"),
    path("<uuid:job_id>/status/", JobStatusPartialView.as_view(), name="job_status_partial"),
    path("<uuid:job_id>/approve-all/", JobApproveAllView.as_view(), name="job_approve_all"),
    path("<uuid:job_id>/start-render/", JobStartRenderView.as_view(), name="job_start_render"),
    # Candidate detail + actions
    path("clips/<uuid:candidate_id>/", CandidateDetailView.as_view(), name="candidate_detail"),
    path("clips/<uuid:candidate_id>/layout/", UpdateLayoutConfigView.as_view(), name="update_layout_config"),
    path("clips/<uuid:candidate_id>/layout/regions/", UpdateLayoutRegionsView.as_view(), name="update_layout_regions"),
    path("clips/<uuid:candidate_id>/layout/reset-crop/", ResetSmartCropView.as_view(), name="reset_smart_crop"),
    path("clips/<uuid:candidate_id>/style/", UpdateStyleConfigView.as_view(), name="update_style_config"),
    path("clips/<uuid:candidate_id>/preview/trigger/", TriggerPreviewView.as_view(), name="trigger_preview"),
    path("clips/<uuid:candidate_id>/preview/status/", PreviewStatusView.as_view(), name="preview_status"),
    path("clips/<uuid:candidate_id>/overlays/add/", AddOverlayView.as_view(), name="add_overlay"),
    path("overlays/<uuid:overlay_id>/update/", UpdateOverlayView.as_view(), name="update_overlay"),
    path("overlays/<uuid:overlay_id>/delete/", DeleteOverlayView.as_view(), name="delete_overlay"),
    path("clips/<uuid:candidate_id>/approve/", CandidateApproveView.as_view(), name="candidate_approve"),
    path("clips/<uuid:candidate_id>/reject/", CandidateRejectView.as_view(), name="candidate_reject"),
    path("clips/<uuid:candidate_id>/undo-reject/", CandidateUndoRejectView.as_view(), name="candidate_undo_reject"),
    path("clips/<uuid:candidate_id>/gates/", UpdateRenderGatesView.as_view(), name="update_render_gates"),
    # Render views
    path("renders/<uuid:render_id>/", RenderDetailView.as_view(), name="render_detail"),
    path("renders/<uuid:render_id>/stages/", StageListPartialView.as_view(), name="stage_list_partial"),
    path("renders/<uuid:render_id>/rerun/<int:stage_order>/", RerunFromStageView.as_view(), name="rerun_from_stage"),
    path("renders/<uuid:render_id>/resume/", ResumeRenderView.as_view(), name="resume_render"),
]
```

- [ ] **Step 4: Run tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/test_views.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/views/candidates.py ***REMOVED***/clipping/urls.py \
        ***REMOVED***/ui/tests/test_views.py
git commit -m "feat(clipping): convert all candidate action views to CBVs"
```

---

## Task 9: Convert clipping/views/renders.py to CBVs + rewrite render_detail.html

**Files:**
- Rewrite: `***REMOVED***/clipping/views/renders.py`
- Rewrite: `***REMOVED***/clipping/templates/clipping/render_detail.html`

- [ ] **Step 1: Rewrite clipping/views/renders.py with CBVs**

Replace entire content of `***REMOVED***/clipping/views/renders.py`:

```python
from __future__ import annotations

import logging

from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView

from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.tasks import render_clip
from ***REMOVED***.ui.mixins import StaffRequiredMixin

logger = logging.getLogger("***REMOVED***.clipping.views")

_TERMINAL_RENDER_STATUSES = frozenset({
    ClipRender.RenderStatus.COMPLETED,
    ClipRender.RenderStatus.FAILED,
    ClipRender.RenderStatus.PAUSED_AT_GATE,
})


class RenderDetailView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/render_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        clip_render = get_object_or_404(
            ClipRender.objects.select_related(
                "candidate__clipping_job__channel",
                "candidate__layout_config",
            ).prefetch_related("stage_results"),
            pk=self.kwargs["render_id"],
        )
        candidate = clip_render.candidate
        context.update({
            "render": clip_render,
            "candidate": candidate,
            "layout": getattr(candidate, "layout_config", None),
            "stages": list(clip_render.stage_results.order_by("stage_order")),
            "is_terminal": clip_render.status in _TERMINAL_RENDER_STATUSES,
            "nav_active": "clipping",
        })
        return context


class StageListPartialView(StaffRequiredMixin, TemplateView):
    """HTMX polling target: refreshes the stage list. Self-stopping when render is terminal."""
    template_name = "clipping/partials/stage_list.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        clip_render = get_object_or_404(
            ClipRender.objects.prefetch_related("stage_results"),
            pk=self.kwargs["render_id"],
        )
        context.update({
            "render": clip_render,
            "stages": list(clip_render.stage_results.order_by("stage_order")),
            "is_terminal": clip_render.status in _TERMINAL_RENDER_STATUSES,
        })
        return context


class RerunFromStageView(StaffRequiredMixin, View):
    """Re-run the render pipeline from the given stage order."""
    def post(self, request: HttpRequest, render_id: str, stage_order: int) -> HttpResponse:
        clip_render = get_object_or_404(ClipRender, pk=render_id)
        clip_render.status = ClipRender.RenderStatus.RUNNING
        clip_render.paused_at_stage = None
        clip_render.last_error = ""
        clip_render.save(update_fields=["status", "paused_at_stage", "last_error", "updated_at"])
        render_clip.delay(
            str(clip_render.candidate_id),
            clip_render_id=str(clip_render.pk),
            start_from_stage=stage_order,
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/app/clipping/renders/{render_id}/"
        return response


class ResumeRenderView(StaffRequiredMixin, View):
    """Continue the pipeline from the stage after the current gate pause."""
    def post(self, request: HttpRequest, render_id: str) -> HttpResponse:
        clip_render = get_object_or_404(ClipRender, pk=render_id)
        if (
            clip_render.status != ClipRender.RenderStatus.PAUSED_AT_GATE
            or clip_render.paused_at_stage is None
        ):
            return HttpResponse("Render is not paused at a gate", status=400)
        next_stage = clip_render.paused_at_stage + 1
        clip_render.status = ClipRender.RenderStatus.RUNNING
        clip_render.paused_at_stage = None
        clip_render.save(update_fields=["status", "paused_at_stage", "updated_at"])
        render_clip.delay(
            str(clip_render.candidate_id),
            clip_render_id=str(clip_render.pk),
            start_from_stage=next_stage,
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/app/clipping/renders/{render_id}/"
        return response
```

- [ ] **Step 2: Rewrite render_detail.html**

Replace entire content of `***REMOVED***/clipping/templates/clipping/render_detail.html`:

```html
{% extends "ui/base.html" %}
{% load static %}

{% block title %}Render — {{ candidate.title|truncatechars:40 }}{% endblock %}

{% block page_header %}
<nav class="flex items-center gap-2 text-sm text-bodytext dark:text-darklink mb-4">
  <a href="{% url 'clipping:job_list' %}" class="hover:text-primary transition-colors">Clipping</a>
  <i class="ti ti-chevron-right text-xs"></i>
  <a href="{% url 'clipping:candidate_detail' candidate.pk %}" class="hover:text-primary transition-colors truncate max-w-xs">
    {{ candidate.title|truncatechars:40 }}
  </a>
  <i class="ti ti-chevron-right text-xs"></i>
  <span class="text-dark dark:text-white">Render</span>
</nav>

<div class="flex items-center gap-4 mb-6">
  <h5 class="card-title text-xl mb-0">Render Detail</h5>
  {% include "ui/partials/status_badge.html" with status=render.status %}
</div>
{% endblock %}

{% block content %}

<div class="grid grid-cols-12 gap-6">

  <!-- Stage list (left) -->
  <div class="col-span-12 lg:col-span-5">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title mb-4">Pipeline Stages</h5>
        <div id="stage-list-container">
          {% include "clipping/partials/stage_list.html" %}
        </div>
      </div>
    </div>
  </div>

  <!-- Preview + gates (right) -->
  <div class="col-span-12 lg:col-span-7">

    <!-- Video preview -->
    <div id="stage-preview" class="card mb-4">
      <div class="card-body">
        {% if render.status == 'COMPLETED' and render.video_file %}
          <h5 class="card-title mb-3">Final Output</h5>
          <video src="{{ render.video_file.url }}" controls
                 class="w-full rounded-md max-h-96 bg-black"></video>
        {% elif render.status == 'PAUSED_AT_GATE' %}
          {% for stage in stages %}
            {% if stage.stage_order == render.paused_at_stage and stage.output_file %}
            <h5 class="card-title text-warning mb-3">
              <i class="ti ti-player-pause me-2"></i>
              Paused at Gate — Stage {{ stage.stage_order }}: {{ stage.stage_name|title }}
            </h5>
            <video src="{{ stage.output_file.url }}" controls
                   class="w-full rounded-md max-h-96 bg-black"></video>
            {% endif %}
          {% endfor %}
        {% else %}
          <div class="text-center py-8">
            <i class="ti ti-video text-4xl text-bodytext dark:text-darklink mb-2 block"></i>
            <p class="text-sm text-bodytext dark:text-darklink">Click a completed stage to preview its output.</p>
          </div>
        {% endif %}
      </div>
    </div>

    <!-- Review gates -->
    <div id="gates-panel" class="card mb-4">
      <div class="card-body">
        {% include "clipping/partials/gates_panel.html" with candidate=candidate render=render %}
      </div>
    </div>

    <!-- Resume / re-run actions when paused -->
    {% if render.status == 'PAUSED_AT_GATE' %}
    <div class="card border-warning">
      <div class="card-body">
        <p class="text-sm text-warning mb-4">
          <i class="ti ti-player-pause me-2"></i>
          Render paused after Stage {{ render.paused_at_stage }}.
          Review the preview above, then continue or adjust config.
        </p>
        <div class="flex gap-3">
          <button class="btn btn-success btn-sm"
                  hx-post="{% url 'clipping:resume_render' render.pk %}"
                  hx-target="body"
                  hx-push-url="true">
            <i class="ti ti-player-play me-1"></i> Continue Pipeline
          </button>
          <a href="{% url 'clipping:candidate_detail' candidate.pk %}"
             class="btn btn-outline-primary btn-sm">
            <i class="ti ti-arrow-left me-1"></i> Edit Config
          </a>
        </div>
      </div>
    </div>
    {% endif %}

  </div>
</div>

{% endblock %}
```

- [ ] **Step 3: Run full test suite**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ui/tests/ ***REMOVED***/clipping/tests/ -v
```

Expected: all tests PASS (no regressions in existing clipping tests)

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/views/renders.py \
        ***REMOVED***/clipping/templates/clipping/render_detail.html
git commit -m "feat(clipping): convert render views to CBVs + rewrite render detail template"
```

---

## Task 10: Update candidate_detail.html + run mypy + final check

**Files:**
- Modify: `***REMOVED***/clipping/templates/clipping/candidate_detail.html` (replace `nav_section` with `nav_active` if present)

- [ ] **Step 1: Fix nav_section → nav_active in candidate_detail.html**

Open `***REMOVED***/clipping/templates/clipping/candidate_detail.html`. Search for any reference to `nav_section` and replace with `nav_active`. (The template itself doesn't set this — it's set by the view's context — but check for any hardcoded references.)

```bash
grep -n "nav_section" ***REMOVED***/clipping/templates/clipping/candidate_detail.html
```

If found, replace `nav_section` with `nav_active` in that file.

Also check all remaining templates:
```bash
grep -rn "nav_section" ***REMOVED***/
```

Replace any remaining `nav_section` context usage in templates with `nav_active`.

- [ ] **Step 2: Run mypy**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run mypy ***REMOVED***/ui/ ***REMOVED***/clipping/views/
```

Expected: no errors. If errors appear, fix them before continuing.

- [ ] **Step 3: Run full test suite**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ -v --tb=short
```

Expected: all tests PASS

- [ ] **Step 4: Lint**

```bash
uv run ruff check . --unsafe-fixes
uv run ruff format .
```

Fix any issues before committing.

- [ ] **Step 5: Run Tailwind build**

```bash
just tailwind-build
```

This recompiles `tailwind.css` with any new utility classes. Required before visual review.

- [ ] **Step 6: Smoke test in browser**

Start the dev server: `just up`

Visit in order and verify each page loads with the new Modernize shell:
1. `http://localhost:8000/app/` — Dashboard: stats cards + active jobs table
2. `http://localhost:8000/app/clipping/` — Clipping list: proper table with badges
3. Any clipping job detail URL — job detail with stage tracker
4. `http://localhost:8000/admin/` — Admin should be unaffected

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(ui): complete dashboard UI revamp — Modernize template, CBVs, dark theme"
```
