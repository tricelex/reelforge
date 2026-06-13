# Django Unfold Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare Django admin with Django Unfold, adding ReelForge branding, by-app sidebar navigation, enriched `BlogPostAdmin`, and a custom dashboard with KPI cards.

**Architecture:** Install `django-unfold`, reorder `INSTALLED_APPS` so auth/axes load before our app (enabling unregister/re-register in `admin.py`), add an `UNFOLD` settings dict with sidebar navigation, create a `dashboard_callback` function and template override.

**Tech Stack:** `django-unfold`, Tailwind CSS (bundled by Unfold), Alpine.js (bundled by Unfold), Google Material Symbols (bundled by Unfold), Django template system.

**Spec:** `docs/superpowers/specs/2026-06-13-django-unfold-admin-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `django-unfold` dependency + mypy override |
| `server/settings/components/common.py` | Modify | Reorder `INSTALLED_APPS`, add unfold apps, add `UNFOLD` config dict |
| `server/settings/components/csp.py` | Modify | Exclude `/admin/` from CSP (Unfold uses Alpine.js inline handlers) |
| `server/apps/main/admin.py` | Modify | Full Unfold admin for BlogPost, User, Group, all three axes models |
| `server/apps/main/dashboard.py` | Create | Dashboard callback — injects `total_posts`, `recent_posts`, `total_users` |
| `server/apps/main/templates/admin/index.html` | Create | Custom dashboard template extending Unfold's admin base |
| `tests/test_apps/test_main/test_dashboard.py` | Create | Unit test for `dashboard_callback` |
| `tests/test_server/test_admin.py` | Modify | Add `test_admin_dashboard_empty` and `test_admin_dashboard_with_posts` |

---

## Task 1: Install django-unfold and Add mypy Override

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency to pyproject.toml**

In `pyproject.toml`, under `[tool.poetry.dependencies]`, add:

```toml
django-unfold = ">=0.40"
```

Also add a mypy override (unfold does not ship typed stubs) after the existing migrations override:

```toml
[[tool.mypy.overrides]]
module = "unfold.*"
ignore_missing_imports = true
```

- [ ] **Step 2: Install the package inside the Docker container**

```bash
docker compose exec web poetry add django-unfold
```

Expected output: `Package operations: 1 install` (no errors).

- [ ] **Step 3: Verify the package is importable**

```bash
docker compose exec web python -c "import unfold; print(unfold.__version__)"
```

Expected: a version string printed (e.g. `0.52.0`).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: add django-unfold dependency"
```

---

## Task 2: Configure INSTALLED_APPS, UNFOLD Settings, and CSP

**Files:**
- Modify: `server/settings/components/common.py`
- Modify: `server/settings/components/csp.py`

**Context:** The critical constraint is that `admin.autodiscover()` processes admin modules in `INSTALLED_APPS` order. Our `server.apps.main.admin` needs to unregister `User`, `Group`, and the three axes models before re-registering them with Unfold. That requires auth and axes to be processed first — so they must appear before `server.apps.main` in `INSTALLED_APPS`.

- [ ] **Step 1: Reorder INSTALLED_APPS and add Unfold apps**

Replace the entire `INSTALLED_APPS` block in `server/settings/components/common.py` with:

```python
INSTALLED_APPS: tuple[str, ...] = (
    # Standard Django apps must come before our apps.
    # Their admin.py files are loaded first by autodiscover(), which lets
    # our admin.py safely call admin.site.unregister() on their models.
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Security — must also precede our apps for the same admin reason:
    'axes',
    # Unfold must come before django.contrib.admin:
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'unfold.contrib.inlines',
    # django-admin:
    'django.contrib.admin',
    'django.contrib.admindocs',
    # Our apps:
    'server.apps.main',
    # django-modern-rest:
    'dmr',
    'corsheaders',
    # Health checks:
    'health_check',
)
```

- [ ] **Step 2: Add imports needed for the UNFOLD config**

At the top of `server/settings/components/common.py`, add these imports (after the existing imports):

```python
from typing import Any

from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse_lazy
```

- [ ] **Step 3: Add the UNFOLD settings dict**

Add the following block at the end of `server/settings/components/common.py`, before the `EMAIL_TIMEOUT` line:

```python
# Django Unfold admin configuration:
# https://unfoldadmin.com/docs/configuration/
UNFOLD: dict[str, Any] = {
    'SITE_TITLE': 'ReelForge',
    'SITE_HEADER': 'ReelForge Admin',
    'SITE_URL': '/',
    'SITE_ICON': {
        'light': lambda request: staticfiles_storage.url(  # type: ignore[misc]
            'main/images/favicon-32x32.png'
        ),
        'dark': lambda request: staticfiles_storage.url(  # type: ignore[misc]
            'main/images/favicon-32x32.png'
        ),
    },
    'DASHBOARD_CALLBACK': 'server.apps.main.dashboard.dashboard_callback',
    'SIDEBAR': {
        'show_search': True,
        'show_all_applications': False,
        'navigation': [
            {
                'title': 'Content',
                'separator': False,
                'items': [
                    {
                        'title': 'Blog Posts',
                        'icon': 'article',
                        'link': reverse_lazy('admin:main_blogpost_changelist'),
                    },
                ],
            },
            {
                'title': 'Auth',
                'separator': True,
                'items': [
                    {
                        'title': 'Users',
                        'icon': 'person',
                        'link': reverse_lazy('admin:auth_user_changelist'),
                    },
                    {
                        'title': 'Groups',
                        'icon': 'group',
                        'link': reverse_lazy('admin:auth_group_changelist'),
                    },
                ],
            },
            {
                'title': 'Security',
                'separator': True,
                'items': [
                    {
                        'title': 'Login Attempts',
                        'icon': 'lock',
                        'link': reverse_lazy(
                            'admin:axes_accessattempt_changelist'
                        ),
                    },
                ],
            },
        ],
    },
}
```

- [ ] **Step 4: Add /admin/ to CSP exclusions**

In `server/settings/components/csp.py`, update the `EXCLUDE_URL_PREFIXES` list:

```python
CONTENT_SECURITY_POLICY: _ContentSecurityPolicy = {
    'EXCLUDE_URL_PREFIXES': [
        '/admin/',
        '/docs/stoplight/',
        '/docs/swagger/',
        '/docs/scalar/',
        '/docs/redoc/',
    ],
    'DIRECTIVES': {
        'default-src': [NONE],
        'script-src': [SELF],
        'style-src': [SELF],
        'img-src': [SELF],
        'font-src': [SELF],
        'connect-src': [],
    },
}
```

- [ ] **Step 5: Run the existing admin tests to check settings are valid**

```bash
docker compose exec web pytest tests/test_server/test_admin.py --no-cov -v
```

Expected: all tests pass. If you see `ImportError` for unfold, check Task 1. If you see `reverse_lazy` errors, check that `reverse_lazy` is imported in common.py.

- [ ] **Step 6: Commit**

```bash
git add server/settings/components/common.py server/settings/components/csp.py
git commit -m "feat(admin): configure django-unfold with ReelForge branding and navigation"
```

---

## Task 3: Write Unfold Admin Classes

**Files:**
- Modify: `server/apps/main/admin.py`

**Context:** We register `BlogPostAdmin` using Unfold's `ModelAdmin`. We also unregister and re-register `User`, `Group`, `AccessAttempt`, `AccessLog`, and `AccessFailureLog` — these were auto-registered by Django auth and axes (now processed first thanks to the INSTALLED_APPS reorder in Task 2).

The import linter places `admin` at the top layer (alongside `urls`), so it may freely import from `models` and below. `axes.admin` and `django.contrib.auth.admin` are external packages exempt from the contract.

- [ ] **Step 1: Replace server/apps/main/admin.py with the full Unfold version**

```python
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin

from server.apps.main.models import BlogPost

# Unregister auth models registered by django.contrib.auth so we can
# re-register them with Unfold's ModelAdmin base for consistent theming.
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(BlogPost)
class BlogPostAdmin(ModelAdmin[BlogPost]):
    list_display = ('title', 'created_at', 'updated_at')
    search_fields = ('title', 'body')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
    compressed_fields = True
    warn_unsaved_changes = True
    fieldsets = (
        ('Content', {'fields': ('title', 'body')}),
        (
            'Metadata',
            {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',),
            },
        ),
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):  # type: ignore[misc]
    pass
```

- [ ] **Step 2: Add axes model re-registrations below the auth block**

Append to `server/apps/main/admin.py`:

```python
from axes.admin import AccessAttemptAdmin as BaseAccessAttemptAdmin
from axes.admin import AccessFailureLogAdmin as BaseAccessFailureLogAdmin
from axes.admin import AccessLogAdmin as BaseAccessLogAdmin
from axes.models import AccessAttempt, AccessFailureLog, AccessLog

# Unregister axes models registered by the axes app so we can re-register
# them with Unfold's ModelAdmin base.
admin.site.unregister(AccessAttempt)
admin.site.unregister(AccessLog)
admin.site.unregister(AccessFailureLog)


@admin.register(AccessAttempt)
class AccessAttemptAdmin(BaseAccessAttemptAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(AccessLog)
class AccessLogAdmin(BaseAccessLogAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(AccessFailureLog)
class AccessFailureLogAdmin(BaseAccessFailureLogAdmin, ModelAdmin):  # type: ignore[misc]
    pass
```

- [ ] **Step 3: Run mypy to verify type annotations**

```bash
docker compose exec web mypy server/apps/main/admin.py
```

Expected: `Success: no issues found` (the `# type: ignore[misc]` comments suppress the known MRO conflict errors from multiple-inheritance with two ModelAdmin bases).

- [ ] **Step 4: Run the admin tests to verify all changelist/add pages still return correct HTTP status**

```bash
docker compose exec web pytest tests/test_server/test_admin.py --no-cov -v
```

Expected: all tests pass (including AccessAttempt, AccessLog, AccessFailureLog add pages returning 403 as defined in `_RESTRICTED_ADMIN_ADD_MODELS`).

- [ ] **Step 5: Run lint**

```bash
docker compose exec web ruff check server/apps/main/admin.py
docker compose exec web lint-imports
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add server/apps/main/admin.py
git commit -m "feat(admin): add Unfold admin classes for BlogPost, User, Group, and axes models"
```

---

## Task 4: Create Dashboard Callback (TDD)

**Files:**
- Create: `tests/test_apps/test_main/test_dashboard.py`
- Create: `server/apps/main/dashboard.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_main/test_dashboard.py`:

```python
from typing import Any
from unittest.mock import MagicMock

import pytest

from server.apps.main.models import BlogPost


@pytest.mark.django_db
def test_dashboard_callback_context_keys_no_data() -> None:
    """Callback injects all required keys even with empty DB."""
    from server.apps.main.dashboard import dashboard_callback

    request = MagicMock()
    result: dict[str, Any] = dashboard_callback(request, {})

    assert isinstance(result['total_posts'], int)
    assert result['total_posts'] == 0
    assert isinstance(result['recent_posts'], list)
    assert result['recent_posts'] == []
    assert isinstance(result['total_users'], int)


@pytest.mark.django_db
def test_dashboard_callback_context_values_with_data() -> None:
    """Callback returns accurate counts and at most 5 recent posts."""
    from server.apps.main.dashboard import dashboard_callback

    BlogPost.objects.create(title='Post A', body='body a')
    BlogPost.objects.create(title='Post B', body='body b')

    request = MagicMock()
    result: dict[str, Any] = dashboard_callback(request, {})

    assert result['total_posts'] == 2
    assert len(result['recent_posts']) == 2
    assert result['recent_posts'][0]['title'] in {'Post A', 'Post B'}
    # Keys present on each recent-post entry:
    assert 'id' in result['recent_posts'][0]
    assert 'title' in result['recent_posts'][0]
    assert 'created_at' in result['recent_posts'][0]
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
docker compose exec web pytest tests/test_apps/test_main/test_dashboard.py --no-cov -v
```

Expected: `ModuleNotFoundError: No module named 'server.apps.main.dashboard'`.

- [ ] **Step 3: Create the dashboard callback**

Create `server/apps/main/dashboard.py`:

```python
from typing import Any

from django.contrib.auth.models import User
from django.http import HttpRequest

from server.apps.main.models import BlogPost


def dashboard_callback(
    request: HttpRequest, context: dict[str, Any]
) -> dict[str, Any]:
    context['total_posts'] = BlogPost.objects.count()
    context['recent_posts'] = list(
        BlogPost.objects.order_by('-created_at').values(
            'id', 'title', 'created_at'
        )[:5]
    )
    context['total_users'] = User.objects.count()
    return context
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
docker compose exec web pytest tests/test_apps/test_main/test_dashboard.py --no-cov -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Run mypy on the new file**

```bash
docker compose exec web mypy server/apps/main/dashboard.py
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Run lint and import checks**

```bash
docker compose exec web ruff check server/apps/main/dashboard.py
docker compose exec web lint-imports
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add server/apps/main/dashboard.py tests/test_apps/test_main/test_dashboard.py
git commit -m "feat(admin): add dashboard callback with blog post and user KPI data"
```

---

## Task 5: Create Dashboard Template and Add Admin Index Test

**Files:**
- Create: `server/apps/main/templates/admin/index.html`
- Modify: `tests/test_server/test_admin.py`

**Context:** Unfold calls `DASHBOARD_CALLBACK` and then renders `admin/index.html`. Our template override extends Django admin's `base_site.html`, which Unfold has already overridden to inject its chrome. The `django-coverage-plugin` measures template coverage, so we need tests for both branches of `{% if recent_posts %}`.

- [ ] **Step 1: Add two admin dashboard tests to tests/test_server/test_admin.py**

Add the following imports at the top of `tests/test_server/test_admin.py` (after existing imports):

```python
from server.apps.main.models import BlogPost
```

Then add these two tests at the bottom of the file:

```python
@pytest.mark.django_db
def test_admin_dashboard_empty(admin_client: Client) -> None:
    """Admin dashboard renders with no data (exercises the empty branch)."""
    response = admin_client.get(reverse('admin:index'))

    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_admin_dashboard_with_posts(admin_client: Client) -> None:
    """Admin dashboard renders with blog post data (exercises the list branch)."""
    BlogPost.objects.create(title='Hello', body='World')

    response = admin_client.get(reverse('admin:index'))

    assert response.status_code == HTTPStatus.OK
    assert b'Hello' in response.content
```

- [ ] **Step 2: Run the new tests to confirm they fail (template not yet created)**

```bash
docker compose exec web pytest tests/test_server/test_admin.py::test_admin_dashboard_empty tests/test_server/test_admin.py::test_admin_dashboard_with_posts --no-cov -v
```

Expected: `TemplateDoesNotExist: admin/index.html` or similar if no override exists, OR they may pass if Unfold ships its own index template. Either way, continue to Step 3.

- [ ] **Step 3: Create the dashboard template**

Create `server/apps/main/templates/admin/index.html`:

```html
{% extends "admin/base_site.html" %}
{% load i18n %}

{% block content %}
<div class="mb-8 mt-6 px-4 sm:px-6 lg:px-8">

  <div class="grid grid-cols-1 gap-5 sm:grid-cols-2 mb-8">

    <div class="overflow-hidden rounded-lg bg-white dark:bg-gray-800 shadow px-4 py-5 sm:p-6">
      <dt class="truncate text-sm font-medium text-gray-500 dark:text-gray-400">
        {% trans "Total Blog Posts" %}
      </dt>
      <dd class="mt-1 text-3xl font-semibold tracking-tight text-gray-900 dark:text-white">
        {{ total_posts }}
      </dd>
    </div>

    <div class="overflow-hidden rounded-lg bg-white dark:bg-gray-800 shadow px-4 py-5 sm:p-6">
      <dt class="truncate text-sm font-medium text-gray-500 dark:text-gray-400">
        {% trans "Total Users" %}
      </dt>
      <dd class="mt-1 text-3xl font-semibold tracking-tight text-gray-900 dark:text-white">
        {{ total_users }}
      </dd>
    </div>

  </div>

  <div class="overflow-hidden rounded-lg bg-white dark:bg-gray-800 shadow">
    <div class="px-4 py-5 sm:p-6">
      <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-4">
        {% trans "Recent Blog Posts" %}
      </h3>
      {% if recent_posts %}
      <ul class="divide-y divide-gray-200 dark:divide-gray-700">
        {% for post in recent_posts %}
        <li class="flex items-center justify-between py-3">
          <span class="text-sm text-gray-900 dark:text-gray-100">{{ post.title }}</span>
          <span class="text-sm text-gray-500 dark:text-gray-400">
            {{ post.created_at|date:"M d, Y" }}
          </span>
        </li>
        {% endfor %}
      </ul>
      {% else %}
      <p class="text-sm text-gray-500 dark:text-gray-400">
        {% trans "No blog posts yet." %}
      </p>
      {% endif %}
    </div>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 4: Run the dashboard tests**

```bash
docker compose exec web pytest tests/test_server/test_admin.py::test_admin_dashboard_empty tests/test_server/test_admin.py::test_admin_dashboard_with_posts --no-cov -v
```

Expected: both tests pass. `test_admin_dashboard_with_posts` verifies `b'Hello'` is in the response body.

- [ ] **Step 5: Commit**

```bash
git add server/apps/main/templates/admin/index.html tests/test_server/test_admin.py
git commit -m "feat(admin): add custom Unfold dashboard template with KPI cards"
```

---

## Task 6: Full Test Suite and Coverage Verification

**Files:** None changed — verification only.

- [ ] **Step 1: Run the complete test suite with coverage**

```bash
docker compose exec web pytest
```

Expected: all tests pass, coverage at 100%.

- [ ] **Step 2: If coverage fails, identify uncovered lines**

```bash
docker compose exec web pytest --cov-report=term-missing
```

Look for uncovered lines in `dashboard.py`, `admin.py`, or the `index.html` template. The most likely gap is a template branch not exercised by tests.

- [ ] **Step 3: Run mypy across the full server package**

```bash
docker compose exec web mypy server
```

Expected: `Success: no issues found`.

- [ ] **Step 4: Run all linting and import checks**

```bash
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web lint-imports
```

Expected: no errors.

- [ ] **Step 5: Final commit if any fixes were needed**

If Step 2–4 required any fixes:

```bash
git add -p  # stage only what changed
git commit -m "fix(admin): address coverage and lint issues from full suite run"
```

---

## Self-Review Notes

- Task 2 reorders `INSTALLED_APPS` — this is the prerequisite for Task 3's unregister calls to succeed. Do not reorder these tasks.
- `axes` registers three models (`AccessAttempt`, `AccessLog`, `AccessFailureLog`); all three must be unregistered and re-registered in Task 3 or the admin changelist tests will render un-themed pages.
- The `# type: ignore[misc]` comments in `admin.py` are intentional — they suppress mypy's MRO conflict error from combining two `ModelAdmin` bases via multiple inheritance.
- Template coverage: `{% if recent_posts %}` has two branches; both are exercised by `test_admin_dashboard_empty` (False branch) and `test_admin_dashboard_with_posts` (True branch).
- No migrations needed — this is a purely presentational change.
