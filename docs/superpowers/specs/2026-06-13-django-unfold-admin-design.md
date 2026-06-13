# Django Unfold Admin — Design Spec

**Date:** 2026-06-13
**Branch:** v2

## Summary

Replace the bare Django admin with Django Unfold: a modern, Tailwind-based admin theme. Adds ReelForge branding, by-app sidebar navigation, full `BlogPostAdmin` with fieldsets and search, explicit admin registrations for built-in models, and a custom dashboard with KPI cards.

---

## 1. Installation & Settings

### Dependency

Add to `pyproject.toml` under `[tool.poetry.dependencies]`:

```toml
django-unfold = "^0.50"
```

Install via `poetry add django-unfold`.

### `INSTALLED_APPS` (`server/settings/components/common.py`)

Unfold must be listed **before** `django.contrib.admin`. Replace the current admin block with:

```python
'unfold',
'unfold.contrib.filters',
'unfold.contrib.forms',
'unfold.contrib.inlines',
'django.contrib.admin',
'django.contrib.admindocs',
```

### `UNFOLD` settings dict (`server/settings/components/common.py`)

Requires two imports at the top of `common.py`:
```python
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse_lazy
```

```python
UNFOLD: dict = {
    'SITE_TITLE': 'ReelForge',
    'SITE_HEADER': 'ReelForge Admin',
    'SITE_URL': '/',
    'SITE_ICON': {
        'light': lambda request: staticfiles_storage.url('main/images/favicon-32x32.png'),
        'dark': lambda request: staticfiles_storage.url('main/images/favicon-32x32.png'),
    },
    'DASHBOARD_CALLBACK': 'server.apps.main.dashboard.dashboard_callback',
    'SIDEBAR': {
        'show_search': True,
        'show_all_applications': False,
        'navigation': [
            {
                'title': 'Content',
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
                'items': [
                    {
                        'title': 'Login Attempts',
                        'icon': 'lock',
                        'link': reverse_lazy('admin:axes_accessattempt_changelist'),
                    },
                ],
            },
        ],
    },
}
```

Icons use Google Material Symbols (bundled by Unfold).

### CSP (`server/settings/components/csp.py`)

Add `/admin/` to `EXCLUDE_URL_PREFIXES`. Unfold uses Alpine.js with inline event handlers and Tailwind inline styles that conflict with strict CSP:

```python
'EXCLUDE_URL_PREFIXES': [
    '/admin/',
    '/docs/stoplight/',
    '/docs/swagger/',
    '/docs/scalar/',
    '/docs/redoc/',
],
```

---

## 2. Admin Classes

### `server/apps/main/admin.py`

`BlogPostAdmin` inherits from `unfold.admin.ModelAdmin` instead of `django.contrib.admin.ModelAdmin`.

```python
from django.contrib import admin
from unfold.admin import ModelAdmin

from server.apps.main.models import BlogPost


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
```

### Built-in model admins (`server/apps/main/admin.py` continued)

Django auto-registers `User`, `Group`, and `AccessAttempt` (via axes). All three must be unregistered before re-registering with Unfold's base. This is done at module load in `admin.py` (not in `ready()`):

```python
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from axes.admin import AccessAttemptAdmin as BaseAccessAttemptAdmin
from axes.models import AccessAttempt

admin.site.unregister(User)
admin.site.unregister(Group)
admin.site.unregister(AccessAttempt)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(AccessAttempt)
class AccessAttemptAdmin(BaseAccessAttemptAdmin, ModelAdmin):  # type: ignore[misc]
    pass
```

The unregister calls must appear after the imports and before the `@admin.register` decorators. Because `axes` uses `default_auto_register` (controlled by the `AXES_ENABLED` and `AXES_VERBOSE` settings), ensure `axes` appears before `server.apps.main` in `INSTALLED_APPS` so axes registers first, giving us something to unregister.

---

## 3. Custom Dashboard

### Callback (`server/apps/main/dashboard.py`)

```python
from typing import Any
from django.contrib.auth.models import User
from django.http import HttpRequest
from server.apps.main.models import BlogPost


def dashboard_callback(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    context['total_posts'] = BlogPost.objects.count()
    context['recent_posts'] = list(
        BlogPost.objects.order_by('-created_at').values('id', 'title', 'created_at')[:5]
    )
    context['total_users'] = User.objects.count()
    return context
```

### Template (`server/apps/main/templates/admin/index.html`)

Extends Unfold's dashboard base. Renders:
- Three KPI stat cards: Total Posts, Total Users, and a "Recent Posts" list card
- Uses Unfold's built-in `{% card %}` / `{% metric %}` template tags (from `unfold.templatetags.unfold`)

---

## 4. Testing & Coverage

### `tests/test_apps/test_main/test_admin.py`

| Test | What it asserts |
|---|---|
| `test_blog_post_admin_list` | GET `/admin/main/blogpost/` → 200 |
| `test_blog_post_admin_detail` | GET `/admin/main/blogpost/<id>/change/` → 200 |
| `test_blog_post_admin_search` | GET `/admin/main/blogpost/?q=test` → 200 |
| `test_user_admin_list` | GET `/admin/auth/user/` → 200 |
| `test_group_admin_list` | GET `/admin/auth/group/` → 200 |
| `test_access_attempt_admin_list` | GET `/admin/axes/accessattempt/` → 200 |

All use `@pytest.mark.django_db` and a superuser fixture. Uses Django's `Client` (not DMRClient — these are admin views, not API views).

### `tests/test_apps/test_main/test_dashboard.py`

| Test | What it asserts |
|---|---|
| `test_dashboard_callback_injects_context` | Calls callback with mock request + `{}`, asserts `total_posts` (int), `recent_posts` (list), `total_users` (int) are present |

---

## 5. Files Changed / Created

| File | Action |
|---|---|
| `pyproject.toml` | Add `django-unfold` dependency |
| `poetry.lock` | Updated by `poetry add` |
| `server/settings/components/common.py` | Add `unfold` apps to `INSTALLED_APPS`, add `UNFOLD` dict |
| `server/settings/components/csp.py` | Add `/admin/` to CSP exclusions |
| `server/apps/main/admin.py` | Full Unfold admin classes |
| `server/apps/main/dashboard.py` | New — dashboard callback |
| `server/apps/main/templates/admin/index.html` | New — dashboard template |
| `tests/test_apps/test_main/test_admin.py` | New — admin integration tests |
| `tests/test_apps/test_main/test_dashboard.py` | New — dashboard unit tests |

---

## Key Constraints

- `django-unfold` must be installed before `django.contrib.admin` in `INSTALLED_APPS`
- No `from __future__ import annotations` in `dashboard.py` (punq resolves annotations at runtime, and even though this file isn't directly DI-registered, maintaining the rule project-wide avoids accidents)
- `axes` auto-registers `AccessAttempt` — must unregister before re-registering with Unfold base
- 100% test coverage required
- Mypy strict mode — all public functions need annotations
- Ruff single quotes, 80-char line length
