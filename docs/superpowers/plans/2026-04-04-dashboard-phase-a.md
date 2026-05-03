# Dashboard Phase A — Foundation + Clipping Approval Flow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `ui` Django app with Tailwind CSS and deliver the full clipping approval flow: real-time job status dashboard, clip candidate review with approve/reject, and render triggering — all without page reloads via HTMX polling.

**Architecture:** Thin `ui` app owns the base layout (top nav + sidebar, Tailwind/HTMX/Alpine). The `clipping` domain app owns its own views, URLs, and templates. HTMX polls job status partials every 2s; polling self-stops when `data-terminal="true"` is set on the polled element. All views require staff login.

**Tech Stack:** Django 5.2, HTMX 2.0.4, Alpine.js 3.14, Tailwind CSS (standalone binary v4), `django-htmx` 1.21, `pytest-django`.

**Phase B** (separate plan): Clip candidate render config (visual layout editor, style config panels, preview generation) + Render detail (per-stage progress, preview, review gates).

---

## File Map

```
reelforge/
  ui/                                       ← NEW Django app
    __init__.py
    apps.py
    urls.py                                 ← /app/ mount, includes domain URLs
    views.py                                ← dashboard home only
    templates/ui/
      base.html                             ← top nav + sidebar + block content
      dashboard.html                        ← home page
      partials/
        active_jobs.html                    ← HTMX-polled active jobs panel
        status_badge.html                   ← reusable FSM status badge
    static/ui/css/
      input.css                             ← Tailwind entry point

  clipping/
    views/                                  ← NEW: replaces single views.py
      __init__.py
      jobs.py                               ← job list, job detail, job_status partial
      candidates.py                         ← approve, reject, start_render
    urls.py                                 ← NEW: /app/clipping/...
    templates/clipping/
      job_list.html
      job_detail.html
      partials/
        job_status.html                     ← HTMX-polled: status + stage tracker
        candidate_row.html                  ← single candidate card (swap target)

  static/css/
    tailwind.css                            ← compiled output, committed

config/
  settings/base.py                          ← add reelforge.ui + django_htmx
  urls.py                                   ← add /app/ include

tailwind.config.js                          ← NEW at project root
bin/tailwindcss                             ← standalone binary, gitignored per-platform
```

---

## Task 1: Tailwind Standalone Binary + Build System

**Files:**
- Create: `tailwind.config.js`
- Create: `reelforge/ui/static/ui/css/input.css`
- Create: `reelforge/static/css/tailwind.css` (compiled, committed)
- Modify: `justfile`
- Modify: `.gitignore`

- [ ] **Step 1.1: Download the Tailwind standalone binary**

```bash
# From project root. Detects your platform:
PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/')
mkdir -p bin
curl -sL "https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.3/tailwindcss-${PLATFORM}-${ARCH}" \
  -o bin/tailwindcss
chmod +x bin/tailwindcss
./bin/tailwindcss --version
```

Expected output: `tailwindcss v4.1.3`

- [ ] **Step 1.2: Add `bin/tailwindcss` to `.gitignore`**

Open `.gitignore` and add at the bottom:

```
# Tailwind standalone binary (platform-specific — each dev downloads their own)
bin/tailwindcss
bin/tailwindcss.exe
```

Commit `bin/.gitkeep` so the directory is tracked:

```bash
touch bin/.gitkeep
git add bin/.gitkeep .gitignore
```

- [ ] **Step 1.3: Create `tailwind.config.js`**

```js
// tailwind.config.js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./reelforge/**/templates/**/*.html",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

- [ ] **Step 1.4: Create the Tailwind entry point**

```bash
mkdir -p reelforge/ui/static/ui/css
```

Create `reelforge/ui/static/ui/css/input.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 1.5: Build the initial CSS**

```bash
mkdir -p reelforge/static/css
./bin/tailwindcss -c tailwind.config.js \
  -i reelforge/ui/static/ui/css/input.css \
  -o reelforge/static/css/tailwind.css
```

Expected: file created, output contains `.text-white`, `.bg-slate-800`, etc.

```bash
grep -c "text-white" reelforge/static/css/tailwind.css
```

Expected: a non-zero number.

- [ ] **Step 1.6: Add `tailwind-watch` and `tailwind-build` to `justfile`**

Add these commands after the existing `lint` command in `justfile`:

```makefile
# tailwind-watch: Rebuild Tailwind CSS on template change (local dev without Docker).
tailwind-watch:
    ./bin/tailwindcss -c tailwind.config.js \
      -i reelforge/ui/static/ui/css/input.css \
      -o reelforge/static/css/tailwind.css \
      --watch

# tailwind-build: Minified production Tailwind build.
tailwind-build:
    ./bin/tailwindcss -c tailwind.config.js \
      -i reelforge/ui/static/ui/css/input.css \
      -o reelforge/static/css/tailwind.css \
      --minify
```

- [ ] **Step 1.7: Commit**

```bash
git add tailwind.config.js reelforge/ui/static/ui/css/input.css \
        reelforge/static/css/tailwind.css justfile .gitignore bin/.gitkeep
git commit -m "build: add Tailwind CSS standalone binary + build pipeline"
```

---

## Task 2: `ui` Django App Scaffolding + `django-htmx`

**Files:**
- Create: `reelforge/ui/__init__.py`
- Create: `reelforge/ui/apps.py`
- Create: `reelforge/ui/urls.py`
- Create: `reelforge/ui/views.py`
- Modify: `config/settings/base.py`
- Modify: `config/urls.py`
- Modify: `pyproject.toml` (add `django-htmx`)
- Test: `tests/ui/test_views.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/ui/__init__.py` (empty) and `tests/ui/test_views.py`:

```python
# tests/ui/test_views.py
from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_dashboard_redirects_anonymous(client):
    response = client.get("/app/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_dashboard_returns_200_for_staff(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        username="staff@test.com",
        email="staff@test.com",
        password="testpass123",
    )
    client.login(username="staff@test.com", password="testpass123")
    response = client.get("/app/")
    assert response.status_code == 200
```

- [ ] **Step 2.2: Run test to confirm failure**

```bash
uv run pytest tests/ui/test_views.py -v
```

Expected: FAIL — `No reverse match` or 404 because `/app/` doesn't exist yet.

- [ ] **Step 2.3: Add `django-htmx` dependency**

```bash
uv add django-htmx
```

- [ ] **Step 2.4: Create the `ui` app files**

`reelforge/ui/__init__.py` — empty file.

`reelforge/ui/apps.py`:

```python
from __future__ import annotations

from django.apps import AppConfig


class UiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reelforge.ui"
    label = "ui"
```

`reelforge/ui/views.py`:

```python
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob


@staff_member_required
def dashboard(request):
    active_jobs = ClippingJob.objects.filter(
        status__in=[
            ClippingJob.Status.INITIALIZING,
            ClippingJob.Status.DOWNLOADING,
            ClippingJob.Status.TRANSCRIBING,
            ClippingJob.Status.ANALYZING,
            ClippingJob.Status.AWAITING_CLIP_APPROVAL,
            ClippingJob.Status.RENDERING,
            ClippingJob.Status.DISTRIBUTING,
        ]
    ).select_related("channel").order_by("-created_at")[:20]

    awaiting_approval = ClippingJob.objects.filter(
        status=ClippingJob.Status.AWAITING_CLIP_APPROVAL,
    ).select_related("channel").order_by("-updated_at")

    completed_today_count = ClippingJob.objects.filter(
        status=ClippingJob.Status.COMPLETED,
        completed_at__date=__import__("django.utils.timezone", fromlist=["now"]).now().date(),
    ).count()

    context = {
        "active_jobs": active_jobs,
        "awaiting_approval": awaiting_approval,
        "active_jobs_count": active_jobs.count(),
        "awaiting_approval_count": awaiting_approval.count(),
        "completed_today_count": completed_today_count,
        "nav_section": "dashboard",
    }
    return render(request, "ui/dashboard.html", context)
```

`reelforge/ui/urls.py`:

```python
from __future__ import annotations

from django.urls import include
from django.urls import path

from reelforge.ui import views

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("clipping/", include("reelforge.clipping.urls", namespace="clipping")),
]
```

- [ ] **Step 2.5: Register the `ui` app and wire up URLs**

In `config/settings/base.py`, add `"reelforge.ui"` and `"django_htmx"` to their respective lists:

```python
# In THIRD_PARTY_APPS (around line 76), add:
"django_htmx",

# In LOCAL_APPS (around line 105), add:
"reelforge.ui",
```

In `config/settings/base.py`, add `HtmxMiddleware` to `MIDDLEWARE`. Find the `MIDDLEWARE` list and append:

```python
# Add after SessionMiddleware or at the end of MIDDLEWARE:
"django_htmx.middleware.HtmxMiddleware",
```

In `config/urls.py`, add the `/app/` mount before the `# Your stuff` comment:

```python
# Add this import at the top:
# (no new import needed — uses include already imported)

# Add in urlpatterns, before "# Your stuff":
path("app/", include("reelforge.ui.urls", namespace="ui")),
```

- [ ] **Step 2.6: Run tests**

```bash
uv run pytest tests/ui/test_views.py -v
```

Expected: PASS for redirect test; dashboard 200 test will fail until template exists.

- [ ] **Step 2.7: Commit**

```bash
git add reelforge/ui/ config/settings/base.py config/urls.py pyproject.toml uv.lock
git commit -m "feat(ui): scaffold ui Django app with django-htmx"
```

---

## Task 3: Base Layout Template

**Files:**
- Create: `reelforge/ui/templates/ui/base.html`
- Create: `reelforge/ui/templates/ui/partials/status_badge.html`

- [ ] **Step 3.1: Create the template directory structure**

```bash
mkdir -p reelforge/ui/templates/ui/partials
```

- [ ] **Step 3.2: Create `reelforge/ui/templates/ui/partials/status_badge.html`**

This partial is included anywhere a status badge is needed. It expects `status` and `status_label` in context, or is called with `{% include ... with status=obj.status %}`.

```html
{% comment %}
Usage: {% include "ui/partials/status_badge.html" with status=job.status %}
{% endcomment %}
{% if status == "INITIALIZING" or status == "DOWNLOADING" or status == "TRANSCRIBING" or status == "ANALYZING" or status == "RENDERING" or status == "DISTRIBUTING" or status == "RUNNING" %}
  <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-900/60 text-indigo-300 border border-indigo-700/40">
    <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse"></span>{{ status|title }}
  </span>
{% elif status == "AWAITING_CLIP_APPROVAL" or status == "PAUSED" %}
  <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-900/60 text-amber-300 border border-amber-700/40">
    <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
    {% if status == "AWAITING_CLIP_APPROVAL" %}Awaiting Approval{% else %}{{ status|title }}{% endif %}
  </span>
{% elif status == "COMPLETED" or status == "RENDERED" or status == "DISTRIBUTED" %}
  <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold bg-green-900/60 text-green-300 border border-green-700/40">
    <span class="w-1.5 h-1.5 rounded-full bg-green-400"></span>{{ status|title }}
  </span>
{% elif status == "FAILED" %}
  <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-900/60 text-red-300 border border-red-700/40">
    <span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>Failed
  </span>
{% else %}
  <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-700 text-slate-400 border border-slate-600">
    {{ status|title }}
  </span>
{% endif %}
```

- [ ] **Step 3.3: Create `reelforge/ui/templates/ui/base.html`**

```html
{% load static %}
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}ReelForge{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'css/tailwind.css' %}">
  <script defer src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"
          integrity="sha384-HGfztofotfshcF7+8n44JQL2oJmowVChPTg48S+jvZoztPfvwD79OC/LTtG6dMp+"
          crossorigin="anonymous"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js"></script>
</head>
<body class="bg-slate-950 text-slate-200 h-full" style="font-family: system-ui, sans-serif;">

<!-- Top Nav -->
<nav class="bg-slate-900 border-b border-slate-700 px-6 py-3 flex items-center gap-6 sticky top-0 z-50">
  <a href="{% url 'ui:dashboard' %}" class="flex items-center gap-2 mr-4">
    <div class="w-7 h-7 bg-indigo-500 rounded-lg flex items-center justify-center text-white text-xs font-bold">RF</div>
    <span class="font-semibold text-white text-sm">ReelForge</span>
  </a>
  <div class="flex items-center gap-1">
    <a href="{% url 'ui:dashboard' %}"
       class="px-3 py-1.5 text-xs font-medium rounded-md {% if nav_section == 'dashboard' %}text-white bg-indigo-600{% else %}text-slate-400 hover:text-white{% endif %}">
      Dashboard
    </a>
    <a href="{% url 'clipping:job_list' %}"
       class="px-3 py-1.5 text-xs font-medium rounded-md {% if nav_section == 'clipping' %}text-white bg-indigo-600{% else %}text-slate-400 hover:text-white{% endif %}">
      Clipping
    </a>
    <a href="#"
       class="px-3 py-1.5 text-xs font-medium rounded-md {% if nav_section == 'youtube' %}text-white bg-indigo-600{% else %}text-slate-400 hover:text-white{% endif %}">
      YouTube
    </a>
    <a href="#"
       class="px-3 py-1.5 text-xs font-medium rounded-md {% if nav_section == 'channels' %}text-white bg-indigo-600{% else %}text-slate-400 hover:text-white{% endif %}">
      Channels
    </a>
  </div>
  <div class="ml-auto flex items-center gap-3">
    <div class="w-7 h-7 bg-slate-700 rounded-full flex items-center justify-center text-xs text-slate-300"
         title="{{ request.user.email }}">
      {{ request.user.email|first|upper }}
    </div>
  </div>
</nav>

<!-- Body: sidebar + content -->
<div class="flex" style="height: calc(100vh - 49px); overflow: hidden;">

  <!-- Left Sidebar -->
  <aside class="w-48 bg-slate-900 border-r border-slate-700 p-3 flex flex-col gap-1 shrink-0 overflow-y-auto">
    {% block sidebar %}
    <!-- Default sidebar: rendered by each view via context or overridden in block -->
    {% endblock sidebar %}
  </aside>

  <!-- Main Content -->
  <main class="flex-1 overflow-y-auto p-6">
    {% block content %}{% endblock content %}
  </main>

</div>

{% block extra_js %}{% endblock extra_js %}
</body>
</html>
```

- [ ] **Step 3.4: Run the dashboard test again**

```bash
uv run pytest tests/ui/test_views.py -v
```

Expected: PASS for the redirect test. The 200 test still needs the dashboard template (next task).

- [ ] **Step 3.5: Commit**

```bash
git add reelforge/ui/templates/
git commit -m "feat(ui): add base layout template with Tailwind + HTMX + Alpine"
```

---

## Task 4: Dashboard Home View + HTMX Polling

**Files:**
- Create: `reelforge/ui/templates/ui/dashboard.html`
- Create: `reelforge/ui/templates/ui/partials/active_jobs.html`
- Modify: `reelforge/ui/views.py` (add `active_jobs_partial` view)
- Modify: `reelforge/ui/urls.py` (add partial URL)
- Test: `tests/ui/test_views.py`

- [ ] **Step 4.1: Add the failing test**

Add to `tests/ui/test_views.py`:

```python
@pytest.mark.django_db
def test_dashboard_active_jobs_partial_requires_staff(client):
    response = client.get("/app/partials/active-jobs/")
    assert response.status_code == 302  # redirects to login


@pytest.mark.django_db
def test_dashboard_active_jobs_partial_returns_200(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        username="staff2@test.com", email="staff2@test.com", password="testpass123"
    )
    client.login(username="staff2@test.com", password="testpass123")
    response = client.get("/app/partials/active-jobs/")
    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
```

- [ ] **Step 4.2: Run to verify failure**

```bash
uv run pytest tests/ui/test_views.py::test_dashboard_active_jobs_partial_returns_200 -v
```

Expected: FAIL — URL does not exist.

- [ ] **Step 4.3: Add `active_jobs_partial` view**

Replace the `dashboard` view's import block and add the partial view in `reelforge/ui/views.py`:

```python
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone

from reelforge.clipping.models import ClippingJob


_ACTIVE_STATUSES = [
    ClippingJob.Status.INITIALIZING,
    ClippingJob.Status.DOWNLOADING,
    ClippingJob.Status.TRANSCRIBING,
    ClippingJob.Status.ANALYZING,
    ClippingJob.Status.AWAITING_CLIP_APPROVAL,
    ClippingJob.Status.RENDERING,
    ClippingJob.Status.DISTRIBUTING,
]


@staff_member_required
def dashboard(request):
    today = timezone.now().date()
    active_jobs = (
        ClippingJob.objects.filter(status__in=_ACTIVE_STATUSES)
        .select_related("channel")
        .order_by("-created_at")[:20]
    )
    awaiting_approval = (
        ClippingJob.objects.filter(status=ClippingJob.Status.AWAITING_CLIP_APPROVAL)
        .select_related("channel")
        .order_by("-updated_at")
    )
    completed_today_count = ClippingJob.objects.filter(
        status=ClippingJob.Status.COMPLETED,
        completed_at__date=today,
    ).count()

    context = {
        "active_jobs": active_jobs,
        "awaiting_approval": awaiting_approval,
        "active_jobs_count": active_jobs.count(),
        "awaiting_approval_count": awaiting_approval.count(),
        "completed_today_count": completed_today_count,
        "nav_section": "dashboard",
    }
    return render(request, "ui/dashboard.html", context)


@staff_member_required
def active_jobs_partial(request):
    """HTMX partial — polled every 2s to refresh the active jobs list."""
    active_jobs = (
        ClippingJob.objects.filter(status__in=_ACTIVE_STATUSES)
        .select_related("channel")
        .order_by("-created_at")[:20]
    )
    return render(request, "ui/partials/active_jobs.html", {"active_jobs": active_jobs})
```

Add the partial URL to `reelforge/ui/urls.py`:

```python
from __future__ import annotations

from django.urls import include
from django.urls import path

from reelforge.ui import views

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("partials/active-jobs/", views.active_jobs_partial, name="active_jobs_partial"),
    path("clipping/", include("reelforge.clipping.urls", namespace="clipping")),
]
```

- [ ] **Step 4.4: Create `reelforge/ui/templates/ui/partials/active_jobs.html`**

This partial is the HTMX swap target. It includes `data-terminal` to stop polling when no active jobs exist. Note: we poll the whole panel — terminal state means "nothing active right now", at which point polling stops. The dashboard full reload will restart polling when navigated to fresh.

```html
{% comment %}
HTMX polled partial. Rendered standalone (no base layout) — returns only this fragment.
Poll stops when data-terminal="true" (no active jobs).
{% endcomment %}
<div id="active-jobs-panel"
     {% if active_jobs %}
     hx-get="{% url 'ui:active_jobs_partial' %}"
     hx-trigger="every 2s"
     hx-swap="outerHTML"
     {% else %}
     data-terminal="true"
     {% endif %}>
  {% if active_jobs %}
    {% for job in active_jobs %}
      <a href="{% url 'clipping:job_detail' job.id %}"
         class="flex items-center gap-3 px-4 py-3 border-b border-slate-700 hover:bg-slate-750 cursor-pointer transition-colors">
        <span class="w-2 h-2 rounded-full shrink-0
          {% if job.status == 'AWAITING_CLIP_APPROVAL' %}bg-amber-400 animate-pulse
          {% elif job.status == 'FAILED' %}bg-red-400
          {% elif job.status == 'COMPLETED' %}bg-green-400
          {% else %}bg-indigo-400 animate-pulse{% endif %}">
        </span>
        <div class="flex-1 min-w-0">
          <p class="text-xs font-medium text-white truncate">{{ job.source_title|default:"Untitled" }}</p>
          <div class="flex items-center gap-2 mt-0.5">
            <span class="text-xs text-slate-500">{{ job.channel.name }}</span>
            <span class="text-slate-600">·</span>
            <span class="text-xs
              {% if job.status == 'AWAITING_CLIP_APPROVAL' %}text-amber-400
              {% elif job.status == 'FAILED' %}text-red-400
              {% else %}text-indigo-400{% endif %}">
              {{ job.get_status_display }}
            </span>
          </div>
        </div>
        <svg class="w-4 h-4 text-slate-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
      </a>
    {% endfor %}
  {% else %}
    <p class="px-4 py-6 text-xs text-slate-500 text-center">No active jobs right now.</p>
  {% endif %}
</div>
```

- [ ] **Step 4.5: Create `reelforge/ui/templates/ui/dashboard.html`**

```html
{% extends "ui/base.html" %}
{% load static %}

{% block sidebar %}
<p class="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 py-1 mt-1">Overview</p>
<a href="{% url 'ui:dashboard' %}"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-white bg-slate-700 rounded-md">
  Home
</a>
<a href="{% url 'clipping:job_list' %}"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  Active Jobs
</a>

<p class="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 py-1 mt-3">Clipping</p>
<a href="{% url 'clipping:job_list' %}"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  All Jobs
</a>
{% if awaiting_approval_count %}
<a href="{% url 'clipping:job_list' %}?status=AWAITING_CLIP_APPROVAL"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  Awaiting Approval
  <span class="ml-auto bg-amber-500 text-black text-xs font-bold px-1.5 rounded-full">
    {{ awaiting_approval_count }}
  </span>
</a>
{% endif %}
{% endblock sidebar %}

{% block content %}
<div class="flex items-center justify-between mb-6">
  <div>
    <h1 class="text-lg font-semibold text-white">Dashboard</h1>
    <p class="text-xs text-slate-500 mt-0.5">{{ request.user.email }}</p>
  </div>
</div>

<!-- Stats row -->
<div class="grid grid-cols-4 gap-4 mb-6">
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
    <p class="text-xs text-slate-400 mb-1">Active Jobs</p>
    <p class="text-2xl font-bold text-white">{{ active_jobs_count }}</p>
  </div>
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
    <p class="text-xs text-slate-400 mb-1">Awaiting Approval</p>
    <p class="text-2xl font-bold text-amber-400">{{ awaiting_approval_count }}</p>
  </div>
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
    <p class="text-xs text-slate-400 mb-1">Completed Today</p>
    <p class="text-2xl font-bold text-green-400">{{ completed_today_count }}</p>
  </div>
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
    <p class="text-xs text-slate-400 mb-1">Approval Queue</p>
    <p class="text-2xl font-bold text-cyan-400">{{ awaiting_approval|length }}</p>
  </div>
</div>

<!-- Two column -->
<div class="grid gap-4" style="grid-template-columns: 1fr 300px;">

  <!-- Active Jobs (polled) -->
  <div class="bg-slate-800 rounded-xl border border-slate-700">
    <div class="flex items-center justify-between px-4 py-3 border-b border-slate-700">
      <h2 class="text-sm font-semibold text-white">Active Jobs</h2>
    </div>
    {% include "ui/partials/active_jobs.html" %}
  </div>

  <!-- Needs Attention -->
  <div class="flex flex-col gap-4">
    <div class="bg-slate-800 rounded-xl border border-amber-800/50">
      <div class="px-4 py-3 border-b border-slate-700">
        <h2 class="text-sm font-semibold text-amber-400">Needs Attention</h2>
      </div>
      {% if awaiting_approval %}
        {% for job in awaiting_approval %}
          <a href="{% url 'clipping:job_detail' job.id %}"
             class="flex items-center gap-2 px-4 py-2.5 border-b border-slate-700 hover:bg-slate-750 cursor-pointer">
            <span class="text-xs text-white truncate flex-1">{{ job.source_title|default:"Untitled"|truncatechars:40 }}</span>
            <span class="text-xs bg-amber-900/60 text-amber-300 px-2 py-0.5 rounded-full shrink-0">
              {{ job.candidates.filter.count }} clips
            </span>
          </a>
        {% endfor %}
      {% else %}
        <p class="px-4 py-4 text-xs text-slate-500">Nothing needs attention.</p>
      {% endif %}
    </div>
  </div>

</div>
{% endblock content %}
```

- [ ] **Step 4.6: Fix the needs-attention candidate count**

The template above has `job.candidates.filter.count` which won't work in templates. Fix by passing annotated data from the view. Update `dashboard` view in `reelforge/ui/views.py` to annotate the awaiting_approval queryset:

```python
from django.db.models import Count

# Replace the awaiting_approval queryset in dashboard():
awaiting_approval = (
    ClippingJob.objects.filter(status=ClippingJob.Status.AWAITING_CLIP_APPROVAL)
    .select_related("channel")
    .annotate(candidate_count=Count("candidates"))
    .order_by("-updated_at")
)
```

Update the template line to:
```html
<span ...>{{ job.candidate_count }} clips</span>
```

- [ ] **Step 4.7: Run tests**

```bash
uv run pytest tests/ui/ -v
```

Expected: all PASS.

- [ ] **Step 4.8: Manual smoke test**

```bash
uv run python manage.py runserver
```

Visit `http://127.0.0.1:8000/app/` — should redirect to login, then show dashboard after login.

- [ ] **Step 4.9: Commit**

```bash
git add reelforge/ui/
git commit -m "feat(ui): dashboard home with HTMX-polled active jobs panel"
```

---

## Task 5: Clipping URL Config + Job List View

**Files:**
- Create: `reelforge/clipping/views/__init__.py`
- Create: `reelforge/clipping/views/jobs.py`
- Create: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/job_list.html`
- Create: `tests/clipping/__init__.py`
- Create: `tests/clipping/test_ui_views.py`

- [ ] **Step 5.1: Write failing tests**

Create `tests/clipping/__init__.py` (empty) and `tests/clipping/test_ui_views.py`:

```python
# tests/clipping/test_ui_views.py
from __future__ import annotations

import pytest
from django.urls import reverse

from reelforge.channels.models import Channel
from reelforge.clipping.models import ClippingJob


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        username="staff@test.com", email="staff@test.com", password="testpass123"
    )
    client.login(username="staff@test.com", password="testpass123")
    return client


@pytest.fixture
def channel(db):
    return Channel.objects.create(name="Test Channel", slug="test-channel")


@pytest.fixture
def clipping_job(db, channel):
    return ClippingJob.objects.create(
        channel=channel,
        source_url="https://youtube.com/watch?v=test",
        source_title="Test Video",
        clips_requested=5,
    )


@pytest.mark.django_db
def test_job_list_requires_staff(client):
    response = client.get("/app/clipping/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_job_list_returns_200(staff_client):
    response = staff_client.get("/app/clipping/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_job_list_shows_jobs(staff_client, clipping_job):
    response = staff_client.get("/app/clipping/")
    assert response.status_code == 200
    assert b"Test Video" in response.content


@pytest.mark.django_db
def test_job_list_filter_by_status(staff_client, clipping_job):
    response = staff_client.get("/app/clipping/?status=AWAITING_CLIP_APPROVAL")
    assert response.status_code == 200
    # clipping_job is INITIALIZING so should not appear
    assert b"Test Video" not in response.content
```

- [ ] **Step 5.2: Run to confirm failure**

```bash
uv run pytest tests/clipping/test_ui_views.py -v
```

Expected: FAIL — URLs not found.

- [ ] **Step 5.3: Create the views module**

```bash
mkdir -p reelforge/clipping/views
touch reelforge/clipping/views/__init__.py
```

Create `reelforge/clipping/views/jobs.py`:

```python
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob


@staff_member_required
def job_list(request):
    status_filter = request.GET.get("status", "")
    jobs = ClippingJob.objects.select_related("channel").order_by("-created_at")

    if status_filter:
        jobs = jobs.filter(status=status_filter)

    status_choices = ClippingJob.Status.choices

    context = {
        "jobs": jobs,
        "status_filter": status_filter,
        "status_choices": status_choices,
        "nav_section": "clipping",
    }
    return render(request, "clipping/job_list.html", context)


@staff_member_required
def job_detail(request, job_id):
    job = get_object_or_404(
        ClippingJob.objects.select_related("channel").prefetch_related(
            "candidates__layout_config",
            "candidates__style_config",
        ),
        id=job_id,
    )
    candidates = job.candidates.order_by("-relevance_score")

    context = {
        "job": job,
        "candidates": candidates,
        "nav_section": "clipping",
        "fsm_stages": [
            ("INITIALIZING", "Init"),
            ("DOWNLOADING", "Download"),
            ("TRANSCRIBING", "Transcribe"),
            ("ANALYZING", "Analyze"),
            ("AWAITING_CLIP_APPROVAL", "Approval"),
            ("RENDERING", "Render"),
            ("DISTRIBUTING", "Distribute"),
            ("COMPLETED", "Done"),
        ],
    }
    return render(request, "clipping/job_detail.html", context)


@staff_member_required
def job_status_partial(request, job_id):
    """HTMX partial — returns just the stage tracker strip."""
    job = get_object_or_404(ClippingJob, id=job_id)
    fsm_stages = [
        ("INITIALIZING", "Init"),
        ("DOWNLOADING", "Download"),
        ("TRANSCRIBING", "Transcribe"),
        ("ANALYZING", "Analyze"),
        ("AWAITING_CLIP_APPROVAL", "Approval"),
        ("RENDERING", "Render"),
        ("DISTRIBUTING", "Distribute"),
        ("COMPLETED", "Done"),
    ]
    terminal = job.status in (
        ClippingJob.Status.COMPLETED,
        ClippingJob.Status.FAILED,
    )
    return render(request, "clipping/partials/job_status.html", {
        "job": job,
        "fsm_stages": fsm_stages,
        "terminal": terminal,
    })
```

- [ ] **Step 5.4: Create `reelforge/clipping/urls.py`**

```python
from __future__ import annotations

from django.urls import path

from reelforge.clipping.views import jobs

app_name = "clipping"

urlpatterns = [
    path("", jobs.job_list, name="job_list"),
    path("<uuid:job_id>/", jobs.job_detail, name="job_detail"),
    path("<uuid:job_id>/status/", jobs.job_status_partial, name="job_status_partial"),
]
```

- [ ] **Step 5.5: Create `reelforge/clipping/templates/clipping/job_list.html`**

```bash
mkdir -p reelforge/clipping/templates/clipping/partials
```

```html
{% extends "ui/base.html" %}

{% block sidebar %}
<p class="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 py-1 mt-1">Clipping</p>
<a href="{% url 'clipping:job_list' %}"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-white bg-slate-700 rounded-md">
  All Jobs
</a>
<a href="{% url 'clipping:job_list' %}?status=AWAITING_CLIP_APPROVAL"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  Awaiting Approval
</a>
<a href="{% url 'clipping:job_list' %}?status=COMPLETED"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  Completed
</a>
{% endblock sidebar %}

{% block content %}
<div class="flex items-center justify-between mb-6">
  <h1 class="text-lg font-semibold text-white">Clipping Jobs</h1>
</div>

<!-- Status filter tabs -->
<div class="flex gap-1 mb-4">
  <a href="{% url 'clipping:job_list' %}"
     class="px-3 py-1.5 text-xs rounded-md {% if not status_filter %}bg-indigo-900/60 text-indigo-300{% else %}text-slate-400 hover:text-white{% endif %}">
    All
  </a>
  {% for value, label in status_choices %}
  <a href="?status={{ value }}"
     class="px-3 py-1.5 text-xs rounded-md {% if status_filter == value %}bg-indigo-900/60 text-indigo-300{% else %}text-slate-400 hover:text-white{% endif %}">
    {{ label }}
  </a>
  {% endfor %}
</div>

<div class="bg-slate-800 rounded-xl border border-slate-700">
  {% if jobs %}
  <div class="divide-y divide-slate-700">
    {% for job in jobs %}
    <a href="{% url 'clipping:job_detail' job.id %}"
       class="flex items-center gap-4 px-4 py-3 hover:bg-slate-750 cursor-pointer">
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium text-white truncate">{{ job.source_title|default:"Untitled" }}</p>
        <p class="text-xs text-slate-500 mt-0.5">{{ job.channel.name }} · {{ job.created_at|date:"M d, Y" }}</p>
      </div>
      {% include "ui/partials/status_badge.html" with status=job.status %}
      <svg class="w-4 h-4 text-slate-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
      </svg>
    </a>
    {% endfor %}
  </div>
  {% else %}
  <p class="px-4 py-8 text-xs text-slate-500 text-center">No jobs found.</p>
  {% endif %}
</div>
{% endblock content %}
```

- [ ] **Step 5.6: Run tests**

```bash
uv run pytest tests/clipping/test_ui_views.py -v
```

Expected: all PASS.

- [ ] **Step 5.7: Commit**

```bash
git add reelforge/clipping/views/ reelforge/clipping/urls.py \
        reelforge/clipping/templates/clipping/job_list.html \
        tests/clipping/
git commit -m "feat(clipping): job list view with status filtering"
```

---

## Task 6: Clipping Job Detail + Pipeline Stage Tracker

**Files:**
- Modify: `reelforge/clipping/views/jobs.py` (already has `job_detail`)
- Create: `reelforge/clipping/templates/clipping/job_detail.html`
- Create: `reelforge/clipping/templates/clipping/partials/job_status.html`
- Create: `reelforge/clipping/templates/clipping/partials/candidate_row.html`

- [ ] **Step 6.1: Write failing tests**

Add to `tests/clipping/test_ui_views.py`:

```python
@pytest.mark.django_db
def test_job_detail_returns_200(staff_client, clipping_job):
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/")
    assert response.status_code == 200
    assert b"Test Video" in response.content


@pytest.mark.django_db
def test_job_status_partial_returns_200(staff_client, clipping_job):
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/status/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_job_status_partial_sets_terminal_for_completed_job(
    staff_client, clipping_job
):
    clipping_job.status = ClippingJob.Status.COMPLETED
    clipping_job.save(update_fields=["status", "updated_at"])
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/status/")
    assert response.status_code == 200
    assert b'data-terminal="true"' in response.content
```

- [ ] **Step 6.2: Run to confirm failure**

```bash
uv run pytest tests/clipping/test_ui_views.py::test_job_detail_returns_200 -v
```

Expected: FAIL — template does not exist.

- [ ] **Step 6.3: Create `reelforge/clipping/templates/clipping/partials/job_status.html`**

This partial renders the stage tracker strip and is the HTMX poll target:

```html
{% comment %}
Polled every 2s while job is active. Sets data-terminal when job is done.
{% endcomment %}
<div id="job-status-{{ job.id }}"
     {% if not terminal %}
     hx-get="{% url 'clipping:job_status_partial' job.id %}"
     hx-trigger="every 2s"
     hx-swap="outerHTML"
     {% else %}
     data-terminal="true"
     {% endif %}>

  <!-- Stage tracker strip -->
  <div class="flex items-center gap-0 px-4 py-4">
    {% for stage_status, stage_label in fsm_stages %}
      {% with is_done=False is_current=False %}
        {% comment %}Determine state by comparing position{% endcomment %}
        <div class="flex flex-col items-center gap-1.5 flex-1 min-w-0">
          {% if job.status == stage_status %}
            <!-- CURRENT stage -->
            <div class="w-6 h-6 rounded-full flex items-center justify-center
              {% if job.status == 'AWAITING_CLIP_APPROVAL' %}bg-amber-500 animate-pulse
              {% elif job.status == 'FAILED' %}bg-red-500
              {% else %}bg-indigo-500 animate-pulse{% endif %}">
              <span class="text-white text-xs">●</span>
            </div>
            <span class="text-xs font-semibold text-center leading-tight truncate
              {% if job.status == 'AWAITING_CLIP_APPROVAL' %}text-amber-400
              {% elif job.status == 'FAILED' %}text-red-400
              {% else %}text-indigo-400{% endif %}">
              {{ stage_label }}
            </span>
          {% else %}
            <!-- Determine if before or after current stage -->
            {% comment %}
            We compare by iterating — stages before current are "done",
            after are "pending". Django templates don't support index comparisons
            directly, so we use a context variable set in the view's fsm_stages list.
            The view passes stages in order; we use a custom tag or accept the simpler
            approach: pass current_stage_index from the view.
            {% endcomment %}
            {% if stage_status in job_completed_stages %}
              <div class="w-6 h-6 rounded-full bg-green-500 flex items-center justify-center">
                <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
                </svg>
              </div>
              <span class="text-xs text-green-400 font-medium text-center leading-tight truncate">{{ stage_label }}</span>
            {% else %}
              <div class="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center">
                <span class="text-xs text-slate-500">–</span>
              </div>
              <span class="text-xs text-slate-500 text-center leading-tight truncate">{{ stage_label }}</span>
            {% endif %}
          {% endif %}
        </div>
        {% if not forloop.last %}
          <div class="h-px w-4 shrink-0
            {% if stage_status in job_completed_stages %}bg-green-500/50
            {% else %}bg-slate-700{% endif %}">
          </div>
        {% endif %}
      {% endwith %}
    {% endfor %}
  </div>

  <!-- Failed error display -->
  {% if job.status == 'FAILED' and job.last_error %}
  <div class="mx-4 mb-3 px-3 py-2 bg-red-900/30 border border-red-700/40 rounded-lg">
    <p class="text-xs text-red-300">{{ job.last_error|truncatechars:200 }}</p>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 6.4: Update `job_detail` and `job_status_partial` views to pass `job_completed_stages`**

The template needs `job_completed_stages` — a set of statuses that come before the current one. Update `reelforge/clipping/views/jobs.py`:

```python
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
```

Update `job_detail` and `job_status_partial` context to include `job_completed_stages`:

```python
# In job_detail():
context = {
    "job": job,
    "candidates": candidates,
    "nav_section": "clipping",
    "fsm_stages": _FSM_STAGE_LABELS,
    "job_completed_stages": _get_completed_stages(job),
}

# In job_status_partial():
terminal = job.status in (ClippingJob.Status.COMPLETED, ClippingJob.Status.FAILED)
return render(request, "clipping/partials/job_status.html", {
    "job": job,
    "fsm_stages": _FSM_STAGE_LABELS,
    "job_completed_stages": _get_completed_stages(job),
    "terminal": terminal,
})
```

- [ ] **Step 6.5: Create `reelforge/clipping/templates/clipping/partials/candidate_row.html`**

This is the HTMX swap target for a single candidate card:

```html
{% comment %}
Single candidate card. id="candidate-{{ candidate.id }}" is the HTMX swap target.
{% endcomment %}
<div id="candidate-{{ candidate.id }}"
     class="flex gap-4 px-4 py-4 border-b border-slate-700
       {% if candidate.approved == True %}border-l-4 border-l-green-600
       {% elif candidate.approved == False %}border-l-4 border-l-red-700 opacity-50
       {% endif %}">

  <!-- Video thumb placeholder (clickable → source at timestamp) -->
  <a href="{{ job.source_url }}#t={{ candidate.start_sec|floatformat:0 }}"
     target="_blank"
     class="w-36 h-20 bg-slate-900 rounded-lg shrink-0 flex items-center justify-center relative border border-slate-700 group">
    <div class="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center group-hover:bg-indigo-500/80 transition-colors z-10">
      <svg class="w-4 h-4 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
    </div>
    <span class="absolute bottom-1 right-1.5 text-xs text-white font-mono bg-black/60 px-1 rounded">
      {{ candidate.duration_sec|floatformat:0 }}s
    </span>
    <span class="absolute top-1 left-1.5 text-xs text-slate-300 font-mono bg-black/40 px-1 rounded">
      {{ candidate.start_sec|floatformat:0 }}s
    </span>
  </a>

  <!-- Content -->
  <div class="flex-1 min-w-0">
    <div class="flex items-start justify-between gap-2">
      <p class="text-sm font-medium text-white {% if candidate.approved == False %}line-through text-slate-500{% endif %}">
        {{ candidate.title }}
      </p>
      <div class="flex items-center gap-2 shrink-0">
        {% if candidate.approved == True %}
          {% include "ui/partials/status_badge.html" with status="COMPLETED" %}
          <button hx-post="{% url 'clipping:candidate_reject' candidate.id %}"
                  hx-target="#candidate-{{ candidate.id }}"
                  hx-swap="outerHTML"
                  class="text-slate-500 hover:text-red-400 transition-colors text-xs">✕</button>
        {% elif candidate.approved == False %}
          <span class="text-xs text-red-400 font-semibold">Rejected</span>
          <button hx-post="{% url 'clipping:candidate_undo_reject' candidate.id %}"
                  hx-target="#candidate-{{ candidate.id }}"
                  hx-swap="outerHTML"
                  class="text-xs text-slate-500 hover:text-slate-300">undo</button>
        {% else %}
          <button hx-post="{% url 'clipping:candidate_approve' candidate.id %}"
                  hx-target="#candidate-{{ candidate.id }}"
                  hx-swap="outerHTML"
                  class="px-2.5 py-1 text-xs bg-green-700 hover:bg-green-600 text-white rounded-md font-medium">
            Approve
          </button>
          <button hx-post="{% url 'clipping:candidate_reject' candidate.id %}"
                  hx-target="#candidate-{{ candidate.id }}"
                  hx-swap="outerHTML"
                  class="px-2.5 py-1 text-xs bg-slate-700 hover:bg-red-900/60 text-slate-300 hover:text-red-300 rounded-md border border-slate-600">
            Reject
          </button>
        {% endif %}
      </div>
    </div>
    <div class="flex items-center gap-3 mt-2">
      <span class="text-xs text-slate-500 font-mono">
        {{ candidate.start_sec|floatformat:0 }}s → {{ candidate.end_sec|floatformat:0 }}s
      </span>
      <span class="text-slate-600">·</span>
      <span class="text-xs text-indigo-400 font-medium">Score {{ candidate.relevance_score|floatformat:1 }}</span>
      {% if candidate.hook_text %}
        <span class="text-slate-600">·</span>
        <span class="text-xs text-slate-500">{{ candidate.hook_text|truncatechars:40 }}</span>
      {% endif %}
    </div>
  </div>
</div>
```

- [ ] **Step 6.6: Create `reelforge/clipping/templates/clipping/job_detail.html`**

```html
{% extends "ui/base.html" %}
{% load static %}

{% block sidebar %}
<p class="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 py-1 mt-1">Clipping</p>
<a href="{% url 'clipping:job_list' %}"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  ← All Jobs
</a>
<a href="{% url 'clipping:job_list' %}?status=AWAITING_CLIP_APPROVAL"
   class="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-md">
  Awaiting Approval
</a>
{% endblock sidebar %}

{% block content %}

<!-- Breadcrumb -->
<div class="flex items-center gap-2 text-xs text-slate-500 mb-4">
  <a href="{% url 'clipping:job_list' %}" class="hover:text-white">Clipping</a>
  <span>/</span>
  <span class="text-slate-300">{{ job.source_title|default:"Untitled"|truncatechars:60 }}</span>
</div>

<!-- Header -->
<div class="flex items-start justify-between mb-4">
  <div>
    <h1 class="text-base font-semibold text-white">{{ job.source_title|default:"Untitled" }}</h1>
    <div class="flex items-center gap-3 mt-1">
      {% if job.source_url %}
        <a href="{{ job.source_url }}" target="_blank" class="text-xs text-indigo-400 hover:text-indigo-300 truncate max-w-xs">
          {{ job.source_url|truncatechars:50 }}
        </a>
      {% endif %}
      <span class="text-slate-600">·</span>
      <span class="text-xs text-slate-400">{{ job.channel.name }}</span>
      {% if job.source_duration_sec %}
        <span class="text-slate-600">·</span>
        <span class="text-xs text-slate-400">{{ job.source_duration_sec|floatformat:0 }}s source</span>
      {% endif %}
    </div>
  </div>
  {% include "ui/partials/status_badge.html" with status=job.status %}
</div>

<!-- Pipeline Stage Tracker (polled) -->
<div class="bg-slate-800 rounded-xl border border-slate-700 mb-6 overflow-hidden">
  {% include "clipping/partials/job_status.html" %}
</div>

<!-- Clip Candidates (shown when in/past approval stage) -->
{% if job.status == 'AWAITING_CLIP_APPROVAL' or job.status == 'RENDERING' or job.status == 'DISTRIBUTING' or job.status == 'COMPLETED' %}
<div class="bg-slate-800 rounded-xl border border-slate-700">
  <div class="flex items-center justify-between px-4 py-3 border-b border-slate-700">
    <div>
      <h2 class="text-sm font-semibold text-white">
        Clip Candidates
        <span class="text-slate-500 font-normal ml-1">{{ candidates|length }} found</span>
      </h2>
      {% if job.status == 'AWAITING_CLIP_APPROVAL' %}
        <p class="text-xs text-slate-400 mt-0.5">Approve clips to include in the render. Rejected clips are skipped.</p>
      {% endif %}
    </div>
    {% if job.status == 'AWAITING_CLIP_APPROVAL' %}
    <div class="flex gap-2">
      <button hx-post="{% url 'clipping:job_approve_all' job.id %}"
              hx-target="#candidates-list"
              hx-swap="innerHTML"
              class="px-3 py-1.5 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-md border border-slate-600">
        Approve All
      </button>
      <button hx-post="{% url 'clipping:job_start_render' job.id %}"
              hx-confirm="Start rendering all approved clips?"
              class="px-3 py-1.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-md">
        Render Approved →
      </button>
    </div>
    {% endif %}
  </div>

  <div id="candidates-list">
    {% for candidate in candidates %}
      {% include "clipping/partials/candidate_row.html" with candidate=candidate job=job %}
    {% empty %}
      <p class="px-4 py-8 text-xs text-slate-500 text-center">No clip candidates found.</p>
    {% endfor %}
  </div>

  <!-- Summary bar -->
  {% if job.status == 'AWAITING_CLIP_APPROVAL' %}
  <div class="px-4 py-3 border-t border-slate-700 flex items-center justify-between bg-slate-800/50">
    <div class="text-xs text-slate-400" id="approval-summary">
      {% with approved_count=candidates|length %}
        {{ approved_count }} total candidates
      {% endwith %}
    </div>
  </div>
  {% endif %}
</div>
{% endif %}

{% endblock content %}
```

- [ ] **Step 6.7: Run tests**

```bash
uv run pytest tests/clipping/test_ui_views.py -v
```

Expected: all PASS.

- [ ] **Step 6.8: Commit**

```bash
git add reelforge/clipping/views/jobs.py \
        reelforge/clipping/templates/clipping/ \
        tests/clipping/test_ui_views.py
git commit -m "feat(clipping): job detail view with polled stage tracker + candidate cards"
```

---

## Task 7: Clip Candidate Approve / Reject + Start Render Actions

**Files:**
- Create: `reelforge/clipping/views/candidates.py`
- Modify: `reelforge/clipping/urls.py`
- Test: `tests/clipping/test_ui_views.py`

- [ ] **Step 7.1: Write failing tests**

Add to `tests/clipping/test_ui_views.py`:

```python
from reelforge.clipping.models import ClipCandidate


@pytest.fixture
def candidate(db, clipping_job):
    return ClipCandidate.objects.create(
        clipping_job=clipping_job,
        start_sec=60.0,
        end_sec=120.0,
        title="Test Clip",
        relevance_score=8.5,
    )


@pytest.mark.django_db
def test_approve_candidate(staff_client, candidate):
    response = staff_client.post(f"/app/clipping/clips/{candidate.id}/approve/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is True
    assert candidate.status == ClipCandidate.CandidateStatus.APPROVED


@pytest.mark.django_db
def test_reject_candidate(staff_client, candidate):
    response = staff_client.post(f"/app/clipping/clips/{candidate.id}/reject/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is False
    assert candidate.status == ClipCandidate.CandidateStatus.REJECTED


@pytest.mark.django_db
def test_undo_reject_candidate(staff_client, candidate):
    # Reject first
    candidate.approved = False
    candidate.status = ClipCandidate.CandidateStatus.REJECTED
    candidate.save(update_fields=["approved", "status", "updated_at"])

    response = staff_client.post(f"/app/clipping/clips/{candidate.id}/undo-reject/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is None
    assert candidate.status == ClipCandidate.CandidateStatus.PROPOSED


@pytest.mark.django_db
def test_approve_all_candidates(staff_client, clipping_job, candidate):
    response = staff_client.post(f"/app/clipping/{clipping_job.id}/approve-all/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is True
```

- [ ] **Step 7.2: Run to confirm failure**

```bash
uv run pytest tests/clipping/test_ui_views.py -k "approve or reject" -v
```

Expected: FAIL — URLs not found.

- [ ] **Step 7.3: Create `reelforge/clipping/views/candidates.py`**

```python
from __future__ import annotations

import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob

logger = logging.getLogger("reelforge.clipping")


@staff_member_required
@require_POST
def candidate_approve(request: HttpRequest, candidate_id: str) -> HttpResponse:
    candidate = get_object_or_404(
        ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
    )
    candidate.approved = True
    candidate.status = ClipCandidate.CandidateStatus.APPROVED
    candidate.approved_by = request.user
    candidate.approved_at = timezone.now()
    candidate.save(update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"])
    logger.info(
        "Clip candidate approved",
        extra={"candidate_id": str(candidate_id), "user": request.user.email},
    )
    return render(request, "clipping/partials/candidate_row.html", {
        "candidate": candidate,
        "job": candidate.clipping_job,
    })


@staff_member_required
@require_POST
def candidate_reject(request: HttpRequest, candidate_id: str) -> HttpResponse:
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
    return render(request, "clipping/partials/candidate_row.html", {
        "candidate": candidate,
        "job": candidate.clipping_job,
    })


@staff_member_required
@require_POST
def candidate_undo_reject(request: HttpRequest, candidate_id: str) -> HttpResponse:
    candidate = get_object_or_404(
        ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
    )
    candidate.approved = None
    candidate.status = ClipCandidate.CandidateStatus.PROPOSED
    candidate.save(update_fields=["approved", "status", "updated_at"])
    return render(request, "clipping/partials/candidate_row.html", {
        "candidate": candidate,
        "job": candidate.clipping_job,
    })


@staff_member_required
@require_POST
def job_approve_all(request: HttpRequest, job_id: str) -> HttpResponse:
    """Approve all PROPOSED candidates for a job. Returns the full candidates list HTML."""
    job = get_object_or_404(ClippingJob, id=job_id)
    now = timezone.now()
    candidates = job.candidates.filter(status=ClipCandidate.CandidateStatus.PROPOSED)
    for candidate in candidates:
        candidate.approved = True
        candidate.status = ClipCandidate.CandidateStatus.APPROVED
        candidate.approved_by = request.user
        candidate.approved_at = now
        candidate.save(update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"])

    all_candidates = job.candidates.order_by("-relevance_score")
    logger.info(
        "Approved all candidates for job",
        extra={"job_id": str(job_id), "count": candidates.count(), "user": request.user.email},
    )
    # Return the full candidates list for hx-target="#candidates-list"
    from django.template.loader import render_to_string
    html = "".join(
        render_to_string("clipping/partials/candidate_row.html", {"candidate": c, "job": job}, request=request)
        for c in all_candidates
    )
    return HttpResponse(html)


@staff_member_required
@require_POST
def job_start_render(request: HttpRequest, job_id: str) -> HttpResponse:
    """Trigger render_clip task for all APPROVED candidates."""
    from django_fsm import TransitionNotAllowed
    from django_fsm import can_proceed

    from reelforge.clipping.tasks import render_clip

    job = get_object_or_404(ClippingJob, id=job_id)
    approved_candidates = job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED)
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
    # Return an HTMX redirect to the job detail page
    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/app/clipping/{job_id}/"
    return response
```

- [ ] **Step 7.4: Update `reelforge/clipping/urls.py`**

```python
from __future__ import annotations

from django.urls import path

from reelforge.clipping.views import candidates
from reelforge.clipping.views import jobs

app_name = "clipping"

urlpatterns = [
    # Job views
    path("", jobs.job_list, name="job_list"),
    path("<uuid:job_id>/", jobs.job_detail, name="job_detail"),
    path("<uuid:job_id>/status/", jobs.job_status_partial, name="job_status_partial"),
    path("<uuid:job_id>/approve-all/", candidates.job_approve_all, name="job_approve_all"),
    path("<uuid:job_id>/start-render/", candidates.job_start_render, name="job_start_render"),
    # Candidate actions
    path("clips/<uuid:candidate_id>/approve/", candidates.candidate_approve, name="candidate_approve"),
    path("clips/<uuid:candidate_id>/reject/", candidates.candidate_reject, name="candidate_reject"),
    path("clips/<uuid:candidate_id>/undo-reject/", candidates.candidate_undo_reject, name="candidate_undo_reject"),
]
```

- [ ] **Step 7.5: Add CSRF token to HTMX POST requests in base template**

HTMX POST requests need the CSRF token. Add this to `base.html` in the `<head>` or before `</body>`:

```html
<!-- Add in base.html after the HTMX script tag: -->
<script>
  document.addEventListener('htmx:configRequest', function(event) {
    event.detail.headers['X-CSRFToken'] = '{{ csrf_token }}';
  });
</script>
```

- [ ] **Step 7.6: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 7.7: Commit**

```bash
git add reelforge/clipping/views/candidates.py \
        reelforge/clipping/urls.py \
        reelforge/ui/templates/ui/base.html \
        tests/clipping/test_ui_views.py
git commit -m "feat(clipping): clip candidate approve/reject/render HTMX actions"
```

---

## Self-Review Notes

After implementing all tasks, verify the following against the spec:

1. **Dashboard home** — stats row, active jobs panel (HTMX polled), needs-attention panel ✓
2. **Clipping job list** — filterable by status ✓
3. **Job detail** — breadcrumb, stage tracker (polled, self-stopping), candidates section ✓
4. **Clip approval** — per-card approve/reject/undo, approve-all, start render ✓
5. **HTMX polling stops** — verify `data-terminal="true"` is set on completed jobs (test 6.1) ✓
6. **CSRF on HTMX POSTs** — added to base.html ✓

**Not in Phase A (Phase B plan):**
- Clip candidate detail page (render mode config, visual editor, style config)
- Render detail page (stage progress, per-stage preview, review gates)
- Model changes for `render_gates` and `PAUSED_AT_GATE`

---

*Phase B plan: `docs/superpowers/plans/2026-04-04-dashboard-phase-b.md` — Visual Layout Editor + Render Stage Oversight*
