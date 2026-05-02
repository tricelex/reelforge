# Clipping API Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the clipping backend so it is fully consumable by a Next.js frontend: token blacklist, global pagination, CORS env var, `/auth/logout/`, `/auth/me/`, social-accounts API, and drf-spectacular `@extend_schema` annotations on all clipping viewsets.

**Architecture:** Settings-first (Task 1 unlocks all other tasks). New auth endpoints and the social-accounts viewset are self-contained additions. OpenAPI annotations are cosmetic-only changes to existing view files — no logic changes.

**Tech Stack:** Django 5.2, DRF, djangorestframework-simplejwt (token_blacklist), drf-spectacular, factory_boy, pytest-django

---

## Test command

All test commands use this prefix (fill in values from your `.envs/.local/` files):

```bash
DATABASE_URL="<value from .envs/.local/.***REMOVED***>" \
CREDENTIAL_ENCRYPTION_KEY="<value from .envs/.local/.django>" \
uv run pytest <path> -v
```

Save them as a shell alias for the session if you prefer:
```bash
export DATABASE_URL="<value from .envs/.local/.***REMOVED***>"
export CREDENTIAL_ENCRYPTION_KEY="<value from .envs/.local/.django>"
```

Then just run `uv run pytest <path> -v`.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `config/settings/base.py` | Modify | Add token_blacklist app, BLACKLIST_AFTER_ROTATION, pagination, CORS_ALLOWED_ORIGINS, ENUM_GENERATE_CHOICE_DESCRIPTION |
| `.envs/.local/.django` | Modify | Add CORS_ALLOWED_ORIGINS=http://localhost:3000 |
| `config/urls.py` | Modify | Add TokenBlacklistView, CurrentUserView, SocialAccountViewSet registration |
| `***REMOVED***/users/api/serializers.py` | Modify | Add CurrentUserSerializer |
| `***REMOVED***/users/api/views.py` | Modify | Add CurrentUserView |
| `***REMOVED***/channels/serializers.py` | **Create** | SocialAccountSerializer |
| `***REMOVED***/channels/views.py` | Modify | Add SocialAccountViewSet (DRF) alongside existing youtube_oauth_callback |
| `***REMOVED***/clipping/tests/test_api.py` | Modify | Fix list tests for paginated response shape; add new tests |
| `***REMOVED***/clipping/views/jobs.py` | Modify | Add @extend_schema_view + @extend_schema on all actions |
| `***REMOVED***/clipping/views/candidates.py` | Modify | Add ListModelMixin (bug fix), add @extend_schema_view + @extend_schema |
| `***REMOVED***/clipping/views/renders.py` | Modify | Add @extend_schema_view + @extend_schema |
| `***REMOVED***/clipping/views/overlays.py` | Modify | Add @extend_schema_view class-level tag |
| `***REMOVED***/clipping/views/assets.py` | Modify | Add @extend_schema_view + @extend_schema on all actions |

---

## Task 1: Settings — token blacklist + pagination + CORS

**Files:**
- Modify: `config/settings/base.py`

- [ ] **Step 1: Add `token_blacklist` to INSTALLED_APPS**

In `config/settings/base.py`, find `THIRD_PARTY_APPS` and add `"rest_framework_simplejwt.token_blacklist",` right after `"rest_framework_simplejwt",`:

```python
# BEFORE (lines ~98-101):
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "corsheaders",

# AFTER:
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
```

- [ ] **Step 2: Add BLACKLIST_AFTER_ROTATION to SIMPLE_JWT**

Find `SIMPLE_JWT = {` and replace the entire block:

```python
# SIMPLE_JWT — replace the existing block
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}
```

- [ ] **Step 3: Add pagination to REST_FRAMEWORK**

Find `REST_FRAMEWORK = {` and replace the entire block:

```python
# REST_FRAMEWORK — replace the existing block
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",  # keep for browsable API / admin
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}
```

- [ ] **Step 4: Add CORS_ALLOWED_ORIGINS and update SPECTACULAR_SETTINGS**

Find the CORS section (around `CORS_URLS_REGEX`) and replace:

```python
# BEFORE:
# django-cors-headers - https://github.com/adamchainz/django-cors-headers#setup
CORS_URLS_REGEX = r"^/api/.*$"

# AFTER:
# django-cors-headers - https://github.com/adamchainz/django-cors-headers#setup
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
```

Then find `SPECTACULAR_SETTINGS = {` and replace the entire block:

```python
# SPECTACULAR_SETTINGS — replace the existing block
SPECTACULAR_SETTINGS = {
    "TITLE": "ReelForge API",
    "DESCRIPTION": "Documentation of API endpoints of ReelForge",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
    "SCHEMA_PATH_PREFIX": "/api/",
    "ENUM_GENERATE_CHOICE_DESCRIPTION": True,
}
```

- [ ] **Step 5: Run the token_blacklist migration**

```bash
just manage migrate
```

Expected output includes: `Applying token_blacklist.0001_initial... OK` (and a few more `token_blacklist` migrations).

- [ ] **Step 6: Commit**

```bash
git add config/settings/base.py
git commit -m "feat(settings): add token_blacklist, global pagination, CORS_ALLOWED_ORIGINS, schema enums"
```

---

## Task 2: Add CORS origin to local env

**Files:**
- Modify: `.envs/.local/.django`

- [ ] **Step 1: Add CORS_ALLOWED_ORIGINS to local env**

Open `.envs/.local/.django` and add this line at the end:

```
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

This file is gitignored — no commit needed.

---

## Task 3: Fix existing list tests broken by pagination

**Files:**
- Modify: `***REMOVED***/clipping/tests/test_api.py`

The global `PAGE_SIZE=20` changes all list responses from `[...]` to `{"count": N, "next": ..., "previous": ..., "results": [...]}`. The existing `test_list_clipping_jobs` test checks `len(response.json()) == 3` which will now fail.

- [ ] **Step 1: Run existing tests to confirm they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_list_clipping_jobs -v
```

Expected: **FAIL** — `TypeError: object of type 'dict' has no len()` (or similar).

- [ ] **Step 2: Update the failing test**

Find `test_list_clipping_jobs` in `***REMOVED***/clipping/tests/test_api.py` and replace it:

```python
@pytest.mark.django_db
def test_list_clipping_jobs(auth_client):
    ClippingJobFactory.create_batch(3)
    response = auth_client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["results"]) == 3
```

- [ ] **Step 3: Run the full test_api.py suite to confirm all tests pass**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All tests **PASS**.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/tests/test_api.py
git commit -m "fix(tests): update list assertions for paginated response shape"
```

---

## Task 4: Auth endpoints — logout + /me/

**Files:**
- Modify: `***REMOVED***/users/api/serializers.py`
- Modify: `***REMOVED***/users/api/views.py`
- Modify: `config/urls.py`
- Modify: `***REMOVED***/clipping/tests/test_api.py` (add new tests)

**Note:** The `User` model has `name` and `email` fields. It has NO `first_name` or `last_name`.

- [ ] **Step 1: Write the failing tests first**

Add these tests to `***REMOVED***/clipping/tests/test_api.py` (at the top, near the other auth tests after `test_non_staff_user_returns_403`):

```python
# ── Auth — logout ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_logout_blacklists_refresh_token(staff_user):
    client = APIClient()
    # Obtain tokens
    response = client.post(
        "/api/v1/auth/token/",
        {"email": staff_user.email, "password": "password"},
        format="json",
    )
    assert response.status_code == 200
    refresh_token = response.json()["refresh"]

    # Logout — blacklist the refresh token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    logout_response = client.post(
        "/api/v1/auth/logout/",
        {"refresh": refresh_token},
        format="json",
    )
    assert logout_response.status_code == 205

    # Attempt to refresh using the blacklisted token — should fail
    refresh_response = client.post(
        "/api/v1/auth/token/refresh/",
        {"refresh": refresh_token},
        format="json",
    )
    assert refresh_response.status_code == 401


# ── Auth — /me/ ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_me_returns_current_user(auth_client, staff_user):
    response = auth_client.get("/api/v1/auth/me/")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == staff_user.email
    assert data["is_staff"] is True
    assert "name" in data
    assert "id" in data
    assert "date_joined" in data
    # oauth_credentials must never be exposed
    assert "oauth_credentials" not in data
    assert "password" not in data


@pytest.mark.django_db
def test_me_requires_authentication():
    client = APIClient()
    response = client.get("/api/v1/auth/me/")
    assert response.status_code == 401
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_logout_blacklists_refresh_token ***REMOVED***/clipping/tests/test_api.py::test_me_returns_current_user ***REMOVED***/clipping/tests/test_api.py::test_me_requires_authentication -v
```

Expected: **FAIL** — `404 Not Found` (endpoints don't exist yet).

- [ ] **Step 3: Add CurrentUserSerializer**

Replace the full content of `***REMOVED***/users/api/serializers.py`:

```python
from __future__ import annotations

from rest_framework import serializers

from ***REMOVED***.users.models import User


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["name", "url"]

        extra_kwargs = {
            "url": {"view_name": "api:user-detail", "lookup_field": "pk"},
        }


class CurrentUserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "email", "name", "is_staff", "date_joined"]
        read_only_fields = ["id", "email", "name", "is_staff", "date_joined"]
```

- [ ] **Step 4: Add CurrentUserView**

Replace the full content of `***REMOVED***/users/api/views.py`:

```python
from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import RetrieveAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.users.api.serializers import CurrentUserSerializer
from ***REMOVED***.users.api.serializers import UserSerializer
from ***REMOVED***.users.models import User


class UserViewSet(RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "pk"

    def get_queryset(self, *_args: Any, **_kwargs: Any) -> Any:
        assert isinstance(self.request.user.id, int)
        return self.queryset.filter(id=self.request.user.id)

    @action(detail=False)
    def me(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(status=status.HTTP_200_OK, data=serializer.data)


@extend_schema(tags=["auth"], summary="Get the currently authenticated user")
class CurrentUserView(RetrieveAPIView):
    serializer_class = CurrentUserSerializer

    def get_object(self) -> User:
        return self.request.user  # type: ignore[return-value]
```

- [ ] **Step 5: Register the new URL patterns**

Replace the full content of `config/urls.py`:

```python
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView

from ***REMOVED***.channels import views as channels_views
from ***REMOVED***.clipping.views import (
    ClipCandidateViewSet,
    ClipLayoutConfigViewSet,
    ClipMediaAssetViewSet,
    ClipMusicAssetViewSet,
    ClipPostViewSet,
    ClipRenderTemplateViewSet,
    ClipRenderViewSet,
    ClipStyleConfigViewSet,
    ClipTimedOverlayViewSet,
    ClippingJobViewSet,
)
from ***REMOVED***.users.api.views import CurrentUserView

# DRF Router
router = DefaultRouter()
router.register(r"clipping/jobs",             ClippingJobViewSet,         basename="clipping-job")
router.register(r"clipping/candidates",       ClipCandidateViewSet,       basename="clip-candidate")
router.register(r"clipping/renders",          ClipRenderViewSet,          basename="clip-render")
router.register(r"clipping/layout-configs",   ClipLayoutConfigViewSet,    basename="clip-layout")
router.register(r"clipping/style-configs",    ClipStyleConfigViewSet,     basename="clip-style")
router.register(r"clipping/overlays",         ClipTimedOverlayViewSet,    basename="clip-overlay")
router.register(r"clipping/media-assets",     ClipMediaAssetViewSet,      basename="clip-media-asset")
router.register(r"clipping/music-assets",     ClipMusicAssetViewSet,      basename="clip-music-asset")
router.register(r"clipping/render-templates", ClipRenderTemplateViewSet,  basename="clip-render-template")
router.register(r"clipping/posts",            ClipPostViewSet,            basename="clip-post")
# social-accounts added in Task 5 after SocialAccountViewSet is created

urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path("about/", TemplateView.as_view(template_name="pages/about.html"), name="about"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("users/", include("***REMOVED***.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    path(
        "oauth/youtube/callback/",
        channels_views.youtube_oauth_callback,
        name="youtube_oauth_callback",
    ),
    path("app/", include("***REMOVED***.ui.urls", namespace="ui")),
    # API v1
    path("api/v1/", include(router.urls)),
    path("api/v1/auth/token/",         TokenObtainPairView.as_view(),  name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(),     name="token_refresh"),
    path("api/v1/auth/logout/",        TokenBlacklistView.as_view(),   name="token_blacklist"),
    path("api/v1/auth/me/",            CurrentUserView.as_view(),      name="current_user"),
    # Legacy API router (users)
    path("api/", include("config.api_router")),
    path("api/auth-token/", include("rest_framework.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]

if settings.DEBUG:
    urlpatterns += [
        path("400/", default_views.bad_request, kwargs={"exception": Exception("Bad Request!")}),
        path("403/", default_views.permission_denied, kwargs={"exception": Exception("Permission Denied")}),
        path("404/", default_views.page_not_found, kwargs={"exception": Exception("Page not Found")}),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls)), *urlpatterns]
```

- [ ] **Step 6: Run the new auth tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_logout_blacklists_refresh_token ***REMOVED***/clipping/tests/test_api.py::test_me_returns_current_user ***REMOVED***/clipping/tests/test_api.py::test_me_requires_authentication -v
```

Expected: All **PASS**.

- [ ] **Step 7: Run the full test_api.py to check for regressions**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All **PASS**.

- [ ] **Step 8: Commit**

```bash
git add config/urls.py ***REMOVED***/users/api/serializers.py ***REMOVED***/users/api/views.py ***REMOVED***/clipping/tests/test_api.py
git commit -m "feat(auth): add /auth/logout/ (token blacklist) and /auth/me/ endpoints"
```

---

## Task 5: Social Accounts API

**Files:**
- Create: `***REMOVED***/channels/serializers.py`
- Modify: `***REMOVED***/channels/views.py`
- Modify: `config/urls.py` (SocialAccountViewSet import + router registration — if not done in Task 4)
- Modify: `***REMOVED***/clipping/tests/test_api.py` (add new tests)

- [ ] **Step 1: Write the failing tests first**

Add these tests to `***REMOVED***/clipping/tests/test_api.py`:

```python
# ── Social Accounts ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_social_accounts_returns_paginated(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    SocialAccountFactory.create_batch(3, is_active=True)
    response = auth_client.get("/api/v1/social-accounts/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 3
    result = data["results"][0]
    # Check expected fields are present
    assert "id" in result
    assert "platform" in result
    assert "platform_display" in result
    assert "handle" in result
    assert "display_name" in result
    assert "is_active" in result
    assert "channel_id" in result
    assert "channel_name" in result
    # Sensitive fields must never appear
    assert "oauth_credentials" not in result


@pytest.mark.django_db
def test_filter_social_accounts_by_platform(auth_client):
    from ***REMOVED***.channels.models import SocialAccount
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    SocialAccountFactory(platform=SocialAccount.Platform.TIKTOK)
    SocialAccountFactory(platform=SocialAccount.Platform.INSTAGRAM)
    response = auth_client.get("/api/v1/social-accounts/?platform=TIKTOK")
    assert response.status_code == 200
    results = response.json()["results"]
    assert all(r["platform"] == "TIKTOK" for r in results)


@pytest.mark.django_db
def test_filter_social_accounts_by_is_active(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    SocialAccountFactory(is_active=True)
    SocialAccountFactory(is_active=False)
    response = auth_client.get("/api/v1/social-accounts/?is_active=true")
    assert response.status_code == 200
    results = response.json()["results"]
    assert all(r["is_active"] is True for r in results)


@pytest.mark.django_db
def test_retrieve_social_account(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    account = SocialAccountFactory()
    response = auth_client.get(f"/api/v1/social-accounts/{account.id}/")
    assert response.status_code == 200
    assert response.json()["id"] == str(account.id)


@pytest.mark.django_db
def test_social_accounts_read_only(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    account = SocialAccountFactory()
    # POST to list — should be 405 Method Not Allowed
    response = auth_client.post("/api/v1/social-accounts/", {}, format="json")
    assert response.status_code == 405
    # DELETE — should be 405
    response = auth_client.delete(f"/api/v1/social-accounts/{account.id}/")
    assert response.status_code == 405
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_list_social_accounts_returns_paginated -v
```

Expected: **FAIL** — `404 Not Found`.

- [ ] **Step 3: Create `***REMOVED***/channels/serializers.py`** (new file)

```python
from __future__ import annotations

from rest_framework import serializers

from ***REMOVED***.channels.models import SocialAccount


class SocialAccountSerializer(serializers.ModelSerializer[SocialAccount]):
    platform_display = serializers.CharField(
        source="get_platform_display",
        read_only=True,
    )
    channel_id = serializers.UUIDField(source="channel.id", read_only=True)
    channel_name = serializers.CharField(source="channel.name", read_only=True)

    class Meta:
        model = SocialAccount
        fields = [
            "id",
            "platform",
            "platform_display",
            "handle",
            "display_name",
            "is_active",
            "channel_id",
            "channel_name",
            "follower_count",
            "last_sync_at",
        ]
        read_only_fields = [
            "id",
            "platform",
            "platform_display",
            "handle",
            "display_name",
            "is_active",
            "channel_id",
            "channel_name",
            "follower_count",
            "last_sync_at",
        ]
```

- [ ] **Step 4: Add `SocialAccountViewSet` to `***REMOVED***/channels/views.py`**

Replace the full content of `***REMOVED***/channels/views.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.urls import reverse
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import SocialAccount
from ***REMOVED***.channels.serializers import SocialAccountSerializer
from ***REMOVED***.channels.services import ChannelSetupService

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger("***REMOVED***.channels")


@staff_member_required
def youtube_oauth_callback(request: HttpRequest) -> HttpResponse:
    """Handle the Google OAuth2 callback after the user authorises access."""
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")

    channel_id: str = request.session.pop("youtube_oauth_channel_id", "")
    expected_state: str = request.session.pop("youtube_oauth_state", "")

    # --- CSRF check ---
    if not state or state != expected_state:
        messages.error(request, "OAuth state mismatch — possible CSRF. Please try again.")
        return redirect(reverse("admin:channels_channel_changelist"))

    if not channel_id:
        messages.error(request, "Session expired — no channel ID found. Please try again.")
        return redirect(reverse("admin:channels_channel_changelist"))

    try:
        channel = Channel.objects.get(pk=channel_id)
    except Channel.DoesNotExist:
        messages.error(request, f"Channel {channel_id} not found.")
        return redirect(reverse("admin:channels_channel_changelist"))

    redirect_uri: str = request.build_absolute_uri(reverse("youtube_oauth_callback"))

    svc = ChannelSetupService(channel)
    try:
        svc.exchange_oauth_code(code=code, redirect_uri=redirect_uri)
        yt_account = channel.get_youtube_account()
        yt_channel_id = yt_account.account_id if yt_account else "unknown"
        messages.success(
            request,
            f"YouTube OAuth configured for '{channel.name}' (channel ID: {yt_channel_id}).",
        )
        logger.info(
            "YouTube OAuth configured successfully",
            extra={
                "channel_id": str(channel.id),
                "youtube_channel_id": yt_channel_id,
            },
        )
    except Exception as exc:
        messages.error(request, f"OAuth setup failed for '{channel.name}': {exc}")
        logger.exception(
            "YouTube OAuth exchange failed",
            extra={"channel_id": str(channel.id), "error": str(exc)},
        )

    return redirect(reverse("admin:channels_channel_change", args=[channel.pk]))


@extend_schema_view(
    list=extend_schema(
        tags=["social-accounts"],
        summary="List social accounts",
        parameters=[
            OpenApiParameter(
                name="platform",
                description="Filter by platform (YOUTUBE, TIKTOK, INSTAGRAM)",
                required=False,
                type=str,
                enum=["YOUTUBE", "TIKTOK", "INSTAGRAM"],
            ),
            OpenApiParameter(
                name="is_active",
                description="Filter by active status (true/false)",
                required=False,
                type=bool,
            ),
        ],
    ),
    retrieve=extend_schema(
        tags=["social-accounts"],
        summary="Get a social account",
    ),
)
class SocialAccountViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    queryset = SocialAccount.objects.select_related("channel").order_by("channel", "platform")
    serializer_class = SocialAccountSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        platform = self.request.query_params.get("platform")
        if platform:
            qs = qs.filter(platform=platform)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs
```

- [ ] **Step 5: Add `SocialAccountViewSet` to `config/urls.py`**

Task 4 intentionally left these out. Add them now that the viewset exists.

Add this import near the top of `config/urls.py` (after the `channels_views` import):

```python
from ***REMOVED***.channels.views import SocialAccountViewSet
```

Add this router registration after the last existing `router.register(...)` line (replacing the comment placeholder):

```python
router.register(r"social-accounts", SocialAccountViewSet, basename="social-account")
```

Remove the comment line `# social-accounts added in Task 5 after SocialAccountViewSet is created`.

- [ ] **Step 6: Run the social accounts tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_list_social_accounts_returns_paginated ***REMOVED***/clipping/tests/test_api.py::test_filter_social_accounts_by_platform ***REMOVED***/clipping/tests/test_api.py::test_filter_social_accounts_by_is_active ***REMOVED***/clipping/tests/test_api.py::test_retrieve_social_account ***REMOVED***/clipping/tests/test_api.py::test_social_accounts_read_only -v
```

Expected: All **PASS**.

- [ ] **Step 7: Run the full test suite**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All **PASS**.

- [ ] **Step 8: Commit**

```bash
git add ***REMOVED***/channels/serializers.py ***REMOVED***/channels/views.py ***REMOVED***/clipping/tests/test_api.py
git commit -m "feat(channels): add SocialAccountViewSet at /api/v1/social-accounts/"
```

---

## Task 6: OpenAPI annotations — jobs.py

**Files:**
- Modify: `***REMOVED***/clipping/views/jobs.py`

No logic changes. This task adds `@extend_schema_view` at the class level and `@extend_schema` on each `@action`.

- [ ] **Step 1: Replace `***REMOVED***/clipping/views/jobs.py` with the annotated version**

```python
from __future__ import annotations

import logging
from typing import Any

from django.http import StreamingHttpResponse
from django_fsm import can_proceed
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.serializers import ClippingJobDetailSerializer
from ***REMOVED***.clipping.serializers import ClippingJobListSerializer
from ***REMOVED***.clipping.sse import emit_job_event
from ***REMOVED***.clipping.sse import job_event_stream
from ***REMOVED***.clipping.tasks import download_source_video
from ***REMOVED***.clipping.tasks import render_clip
from ***REMOVED***.clipping.tasks import transcribe_video

logger = logging.getLogger("***REMOVED***.clipping.api")


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-jobs"],
        summary="List clipping jobs",
        responses={200: ClippingJobListSerializer(many=True)},
    ),
    create=extend_schema(
        tags=["clipping-jobs"],
        summary="Create a clipping job and start download",
        responses={201: ClippingJobDetailSerializer},
    ),
    retrieve=extend_schema(
        tags=["clipping-jobs"],
        summary="Get a clipping job with candidates",
        responses={200: ClippingJobDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["clipping-jobs"],
        summary="Partially update a clipping job",
        responses={200: ClippingJobDetailSerializer},
    ),
    destroy=extend_schema(
        tags=["clipping-jobs"],
        summary="Delete a clipping job",
        responses={204: None},
    ),
)
class ClippingJobViewSet(ModelViewSet):
    queryset = ClippingJob.objects.select_related("social_account").order_by("-created_at")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClippingJobDetailSerializer
        return ClippingJobListSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def perform_create(self, serializer) -> None:
        job: ClippingJob = serializer.save()
        if can_proceed(job.begin_download):
            job.begin_download()
            job.save(update_fields=["status", "started_at", "updated_at"])
        download_source_video.delay(str(job.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        logger.info("ClippingJob created", extra={"job_id": str(job.id)})

    @extend_schema(
        tags=["clipping-jobs"],
        summary="Dispatch render_clip for all approved candidates",
        request=None,
        responses={
            200: inline_serializer(
                name="StartRenderResponse",
                fields={
                    "dispatched_renders": drf_serializers.IntegerField(),
                    "candidate_ids": drf_serializers.ListField(child=drf_serializers.UUIDField()),
                    "job_status": drf_serializers.CharField(),
                },
            ),
            400: OpenApiResponse(description="No approved candidates or invalid FSM state"),
        },
    )
    @action(detail=True, methods=["post"], url_path="start-render")
    def start_render(self, request: Request, pk: str | None = None) -> Response:
        """Dispatch render_clip for all APPROVED candidates and begin_rendering FSM transition."""
        job: ClippingJob = self.get_object()
        approved = list(
            job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED)
        )
        if not approved:
            return Response(
                {"detail": "No approved candidates found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not can_proceed(job.begin_rendering):
            return Response(
                {"detail": f"Cannot begin rendering from state {job.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.begin_rendering()
        job.save(update_fields=["status", "updated_at"])
        for candidate in approved:
            render_clip.delay(str(candidate.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        return Response(
            {
                "dispatched_renders": len(approved),
                "candidate_ids": [str(c.id) for c in approved],
                "job_status": job.status,
            }
        )

    @extend_schema(
        tags=["clipping-jobs"],
        summary="Approve all PROPOSED candidates on this job",
        request=None,
        responses={
            200: inline_serializer(
                name="ApproveAllResponse",
                fields={"approved_count": drf_serializers.IntegerField()},
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="approve-all")
    def approve_all(self, request: Request, pk: str | None = None) -> Response:
        """Approve all PROPOSED candidates on this job."""
        job: ClippingJob = self.get_object()
        from django.utils import timezone

        updated = job.candidates.filter(
            status=ClipCandidate.CandidateStatus.PROPOSED
        ).update(
            status=ClipCandidate.CandidateStatus.APPROVED,
            approved=True,
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        return Response({"approved_count": updated})

    @extend_schema(
        tags=["clipping-jobs"],
        summary="Retry a failed job from transcription or analysis stage",
        request=inline_serializer(
            name="RetryRequest",
            fields={
                "from_stage": drf_serializers.ChoiceField(
                    choices=["transcription", "analysis"],
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="RetryResponse",
                fields={
                    "job_status": drf_serializers.CharField(),
                    "retrying": drf_serializers.CharField(),
                },
            ),
            400: OpenApiResponse(description="Invalid FSM state for retry"),
        },
    )
    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request: Request, pk: str | None = None) -> Response:
        """Retry a failed job. Body: {"from_stage": "transcription" | "analysis"}"""
        job: ClippingJob = self.get_object()
        from_stage = request.data.get("from_stage", "transcription")
        if from_stage == "analysis":
            if not can_proceed(job.retry_analysis):
                return Response(
                    {"detail": f"Cannot retry analysis from state {job.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.retry_analysis()
            job.save(update_fields=["status", "last_error", "updated_at"])
            from ***REMOVED***.clipping.tasks import analyze_clips

            analyze_clips.delay(str(job.id))
        else:
            if not can_proceed(job.retry_transcription):
                return Response(
                    {"detail": f"Cannot retry transcription from state {job.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.retry_transcription()
            job.save(update_fields=["status", "last_error", "updated_at"])
            transcribe_video.delay(str(job.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        return Response({"job_status": job.status, "retrying": from_stage})

    @extend_schema(
        tags=["clipping-jobs"],
        summary="SSE stream — real-time job events via Redis pub/sub",
        description=(
            "Server-Sent Events stream. Connect with EventSource. "
            "Each event is a JSON payload: `{type, job_id, ...}`. "
            "Event types: status_changed, analysis_complete, job_failed, "
            "render_paused, render_complete, render_failed, post_complete, preview_ready."
        ),
        responses={200: OpenApiTypes.STR},
    )
    @action(detail=True, methods=["get"], url_path="stream")
    def stream(self, request: Request, pk: str | None = None) -> StreamingHttpResponse:
        """SSE endpoint. Streams real-time job events from Redis pub/sub."""
        job: ClippingJob = self.get_object()
        response = StreamingHttpResponse(
            job_event_stream(str(job.id)),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
```

- [ ] **Step 2: Run the jobs tests to confirm nothing broke**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py -k "job" -v
```

Expected: All **PASS**.

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/views/jobs.py
git commit -m "feat(openapi): annotate ClippingJobViewSet with @extend_schema"
```

---

## Task 7: OpenAPI annotations — candidates.py + ListModelMixin bug fix

**Files:**
- Modify: `***REMOVED***/clipping/views/candidates.py`

**Bug fix included:** `ClipCandidateViewSet` was missing `ListModelMixin` — the `GET /api/v1/clipping/candidates/` list endpoint was registered but returning 405. This task fixes that.

- [ ] **Step 1: Write a failing test for the candidates list endpoint**

Add to `***REMOVED***/clipping/tests/test_api.py`:

```python
# ── ClipCandidate list ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_candidates_by_job(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job)
    ClipCandidateFactory(clipping_job=job)
    # Candidate from a different job — should not appear
    ClipCandidateFactory()
    response = auth_client.get(f"/api/v1/clipping/candidates/?job={job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["results"]) == 2
```

- [ ] **Step 2: Run to confirm it fails**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_list_candidates_by_job -v
```

Expected: **FAIL** — 405 Method Not Allowed (ListModelMixin missing).

- [ ] **Step 3: Replace `***REMOVED***/clipping/views/candidates.py` with annotated + fixed version**

```python
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone
from django_fsm import can_proceed
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.serializers import ClipCandidateDetailSerializer
from ***REMOVED***.clipping.serializers import ClipCandidateListSerializer
from ***REMOVED***.clipping.serializers import ClipLayoutConfigSerializer
from ***REMOVED***.clipping.serializers import ClipStyleConfigSerializer
from ***REMOVED***.clipping.tasks import preview_clip_layout
from ***REMOVED***.clipping.tasks import preview_clip_style

logger = logging.getLogger("***REMOVED***.clipping.api")


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-candidates"],
        summary="List clip candidates (filter by ?job= and ?status=)",
        parameters=[
            OpenApiParameter(name="job", description="Filter by ClippingJob UUID", required=False, type=str),
            OpenApiParameter(
                name="status",
                description="Filter by candidate status",
                required=False,
                type=str,
                enum=["PROPOSED", "APPROVED", "REJECTED", "RENDERING", "RENDERED", "DISTRIBUTING", "DISTRIBUTED"],
            ),
        ],
        responses={200: ClipCandidateListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["clipping-candidates"],
        summary="Get a clip candidate with full layout/style config",
        responses={200: ClipCandidateDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["clipping-candidates"],
        summary="Update clip candidate fields (title, hook_text, render_gates, etc.)",
        responses={200: ClipCandidateDetailSerializer},
    ),
)
class ClipCandidateViewSet(ListModelMixin, RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipCandidate.objects.select_related(
        "clipping_job__social_account",
        "approved_by",
        "layout_config",
        "style_config",
    ).prefetch_related("timed_overlays")
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClipCandidateDetailSerializer
        return ClipCandidateListSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        job_id = self.request.query_params.get("job")
        if job_id:
            qs = qs.filter(clipping_job_id=job_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Approve a clip candidate",
        request=None,
        responses={
            200: inline_serializer(
                name="CandidateApproveResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "status": drf_serializers.CharField(),
                    "approved": drf_serializers.BooleanField(),
                    "approved_at": drf_serializers.DateTimeField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.APPROVED
        candidate.approved = True
        candidate.approved_at = timezone.now()
        candidate.approved_by = request.user
        candidate.save(update_fields=["status", "approved", "approved_at", "approved_by", "updated_at"])
        return Response({
            "id": str(candidate.id),
            "status": candidate.status,
            "approved": candidate.approved,
            "approved_at": candidate.approved_at,
        })

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Reject a clip candidate",
        request=inline_serializer(
            name="CandidateRejectRequest",
            fields={"reason": drf_serializers.CharField(required=False, default="")},
        ),
        responses={
            200: inline_serializer(
                name="CandidateRejectResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "status": drf_serializers.CharField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        reason = request.data.get("reason", "")
        candidate.status = ClipCandidate.CandidateStatus.REJECTED
        candidate.approved = False
        candidate.rejection_reason = reason
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Undo rejection — reset candidate to PROPOSED",
        request=None,
        responses={
            200: inline_serializer(
                name="UndoRejectResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "status": drf_serializers.CharField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="undo-reject")
    def undo_reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.PROPOSED
        candidate.approved = None
        candidate.rejection_reason = ""
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Queue a layout preview image generation task",
        request=None,
        responses={
            200: inline_serializer(
                name="TriggerPreviewResponse",
                fields={
                    "queued": drf_serializers.BooleanField(),
                    "layout_config_id": drf_serializers.UUIDField(),
                },
            ),
            400: OpenApiResponse(description="No layout config found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="trigger-preview")
    def trigger_preview(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        if not hasattr(candidate, "layout_config"):
            return Response(
                {"detail": "No layout config found for this candidate."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        preview_clip_layout.delay(str(candidate.layout_config.id))
        return Response({"queued": True, "layout_config_id": str(candidate.layout_config.id)})

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Check if layout preview image is ready",
        responses={
            200: inline_serializer(
                name="PreviewStatusResponse",
                fields={
                    "ready": drf_serializers.BooleanField(),
                    "preview_url": drf_serializers.URLField(allow_null=True),
                },
            ),
        },
    )
    @action(detail=True, methods=["get"], url_path="preview-status")
    def preview_status(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        lc = getattr(candidate, "layout_config", None)
        if lc is None:
            return Response({"ready": False, "preview_url": None})
        preview_url = None
        if lc.preview_image:
            preview_url = request.build_absolute_uri(lc.preview_image.url)
        return Response({"ready": bool(lc.preview_image), "preview_url": preview_url})


@extend_schema_view(
    retrieve=extend_schema(
        tags=["clipping-candidates"],
        summary="Get layout config for a candidate",
    ),
    partial_update=extend_schema(
        tags=["clipping-candidates"],
        summary="Update layout config (render_mode, crop coords, stack regions)",
    ),
)
class ClipLayoutConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipLayoutConfig.objects.select_related("candidate")
    serializer_class = ClipLayoutConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Clear manual crop coordinates (reset to auto-detect)",
        request=None,
        responses={200: ClipLayoutConfigSerializer},
    )
    @action(detail=True, methods=["post"], url_path="reset-crop")
    def reset_crop(self, request: Request, pk: str | None = None) -> Response:
        lc: ClipLayoutConfig = self.get_object()
        lc.manual_crop_x = None
        lc.manual_crop_y = None
        lc.manual_crop_w = None
        lc.manual_crop_h = None
        lc.save(update_fields=["manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at"])
        return Response(ClipLayoutConfigSerializer(lc, context={"request": request}).data)


@extend_schema_view(
    retrieve=extend_schema(
        tags=["clipping-candidates"],
        summary="Get style config for a candidate",
    ),
    partial_update=extend_schema(
        tags=["clipping-candidates"],
        summary="Update style config (captions, watermark, music, etc.)",
    ),
)
class ClipStyleConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipStyleConfig.objects.select_related(
        "candidate", "render_template", "intro_asset", "outro_asset", "music_asset"
    )
    serializer_class = ClipStyleConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["clipping-candidates"],
        summary="Re-seed all style fields from a render template",
        request=inline_serializer(
            name="ApplyTemplateRequest",
            fields={"template_id": drf_serializers.UUIDField()},
        ),
        responses={
            200: ClipStyleConfigSerializer,
            400: OpenApiResponse(description="template_id is required"),
            404: OpenApiResponse(description="Template not found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="apply-template")
    def apply_template(self, request: Request, pk: str | None = None) -> Response:
        """Re-seed all style fields from a given render template."""
        config: ClipStyleConfig = self.get_object()
        template_id = request.data.get("template_id")
        if not template_id:
            return Response(
                {"detail": "template_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            template = ClipRenderTemplate.objects.get(id=template_id)
        except ClipRenderTemplate.DoesNotExist:
            return Response({"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND)

        style_fields = template.to_style_defaults()
        for field_name, value in style_fields.items():
            setattr(config, field_name, value)
        config.render_template = template
        config.save(update_fields=[*style_fields.keys(), "render_template", "updated_at"])
        return Response(ClipStyleConfigSerializer(config, context={"request": request}).data)
```

- [ ] **Step 4: Run the new candidates list test + full suite**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py::test_list_candidates_by_job ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All **PASS**.

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/views/candidates.py ***REMOVED***/clipping/tests/test_api.py
git commit -m "feat(openapi): annotate candidate/layout/style viewsets; fix missing ListModelMixin on ClipCandidateViewSet"
```

---

## Task 8: OpenAPI annotations — renders.py

**Files:**
- Modify: `***REMOVED***/clipping/views/renders.py`

- [ ] **Step 1: Replace `***REMOVED***/clipping/views/renders.py` with the annotated version**

```python
from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.serializers import ClipRenderSerializer
from ***REMOVED***.clipping.tasks import render_clip

logger = logging.getLogger("***REMOVED***.clipping.api")


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-renders"],
        summary="List renders (filter by ?candidate=)",
        parameters=[
            OpenApiParameter(
                name="candidate",
                description="Filter renders by ClipCandidate UUID",
                required=False,
                type=str,
            ),
        ],
        responses={200: ClipRenderSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["clipping-renders"],
        summary="Get a render with all stage results",
        responses={200: ClipRenderSerializer},
    ),
)
class ClipRenderViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    queryset = ClipRender.objects.select_related("candidate").prefetch_related("stage_results")
    serializer_class = ClipRenderSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        candidate_id = self.request.query_params.get("candidate")
        if candidate_id:
            qs = qs.filter(candidate_id=candidate_id)
        return qs

    @extend_schema(
        tags=["clipping-renders"],
        summary="Resume a PAUSED_AT_GATE render from the next stage",
        request=None,
        responses={
            200: inline_serializer(
                name="ResumeRenderResponse",
                fields={
                    "resumed": drf_serializers.BooleanField(),
                    "start_from_stage": drf_serializers.IntegerField(),
                },
            ),
            400: OpenApiResponse(description="Render is not paused or paused_at_stage not set"),
        },
    )
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str | None = None) -> Response:
        """Resume a PAUSED_AT_GATE render from the next stage."""
        render: ClipRender = self.get_object()
        if render.status != ClipRender.RenderStatus.PAUSED_AT_GATE:
            return Response(
                {"detail": f"Render is not paused. Current status: {render.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if render.paused_at_stage is None:
            return Response(
                {"detail": "paused_at_stage is not set."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        next_stage = render.paused_at_stage + 1
        render_clip.delay(
            str(render.candidate_id),
            start_from_stage=next_stage,
            clip_render_id=str(render.id),
        )
        return Response({"resumed": True, "start_from_stage": next_stage})

    @extend_schema(
        tags=["clipping-renders"],
        summary="Re-run a render from a specific stage (1–10)",
        request=None,
        responses={
            200: inline_serializer(
                name="RerunRenderResponse",
                fields={
                    "rerunning": drf_serializers.BooleanField(),
                    "start_from_stage": drf_serializers.IntegerField(),
                },
            ),
            400: OpenApiResponse(description="stage_order out of range 1–10"),
        },
    )
    @action(detail=True, methods=["post"], url_path=r"rerun/(?P<stage_order>[0-9]+)")
    def rerun(self, request: Request, pk: str | None = None, stage_order: str = "1") -> Response:
        """Re-run a render from a specific stage."""
        render: ClipRender = self.get_object()
        start = int(stage_order)
        if not 1 <= start <= 10:
            return Response(
                {"detail": "stage_order must be between 1 and 10."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        render_clip.delay(
            str(render.candidate_id),
            start_from_stage=start,
            clip_render_id=str(render.id),
        )
        return Response({"rerunning": True, "start_from_stage": start})

    @extend_schema(
        tags=["clipping-renders"],
        summary="Get download URL for the final rendered video",
        responses={
            200: inline_serializer(
                name="DownloadUrlResponse",
                fields={"download_url": drf_serializers.URLField()},
            ),
            404: OpenApiResponse(description="Render has no video file yet"),
        },
    )
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> Response:
        """Return a URL for downloading the final render file."""
        render: ClipRender = self.get_object()
        if not render.video_file:
            return Response(
                {"detail": "Render has no video file yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        url = request.build_absolute_uri(render.video_file.url)
        return Response({"download_url": url})
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All **PASS**.

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/views/renders.py
git commit -m "feat(openapi): annotate ClipRenderViewSet with @extend_schema"
```

---

## Task 9: OpenAPI annotations — overlays.py + assets.py

**Files:**
- Modify: `***REMOVED***/clipping/views/overlays.py`
- Modify: `***REMOVED***/clipping/views/assets.py`

- [ ] **Step 1: Replace `***REMOVED***/clipping/views/overlays.py`**

```python
from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import extend_schema
from rest_framework.viewsets import ModelViewSet

from ***REMOVED***.clipping.models import ClipTimedOverlay
from ***REMOVED***.clipping.serializers import ClipTimedOverlaySerializer


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-overlays"],
        summary="List timed overlays (filter by ?candidate=)",
        parameters=[
            OpenApiParameter(
                name="candidate",
                description="Filter by ClipCandidate UUID",
                required=False,
                type=str,
            ),
        ],
    ),
    create=extend_schema(tags=["clipping-overlays"], summary="Create a timed overlay"),
    retrieve=extend_schema(tags=["clipping-overlays"], summary="Get a timed overlay"),
    partial_update=extend_schema(tags=["clipping-overlays"], summary="Update a timed overlay"),
    destroy=extend_schema(tags=["clipping-overlays"], summary="Delete a timed overlay"),
)
class ClipTimedOverlayViewSet(ModelViewSet):
    queryset = ClipTimedOverlay.objects.select_related("candidate")
    serializer_class = ClipTimedOverlaySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        candidate_id = self.request.query_params.get("candidate")
        if candidate_id:
            qs = qs.filter(candidate_id=candidate_id)
        return qs
```

- [ ] **Step 2: Replace `***REMOVED***/clipping/views/assets.py`**

```python
from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.serializers import ClipMediaAssetSerializer
from ***REMOVED***.clipping.serializers import ClipMusicAssetSerializer
from ***REMOVED***.clipping.serializers import ClipPostSerializer
from ***REMOVED***.clipping.serializers import ClipRenderTemplateSerializer
from ***REMOVED***.clipping.tasks import sync_clip_analytics

logger = logging.getLogger("***REMOVED***.clipping.api")


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-assets"],
        summary="List media assets (filter by ?asset_type=INTRO or OUTRO)",
        parameters=[
            OpenApiParameter(
                name="asset_type",
                description="Filter by asset type",
                required=False,
                type=str,
                enum=["INTRO", "OUTRO"],
            ),
        ],
    ),
    create=extend_schema(tags=["clipping-assets"], summary="Upload a media asset"),
    retrieve=extend_schema(tags=["clipping-assets"], summary="Get a media asset"),
    partial_update=extend_schema(tags=["clipping-assets"], summary="Update a media asset"),
    destroy=extend_schema(tags=["clipping-assets"], summary="Delete a media asset"),
)
class ClipMediaAssetViewSet(ModelViewSet):
    queryset = ClipMediaAsset.objects.order_by("asset_type", "name")
    serializer_class = ClipMediaAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        asset_type = self.request.query_params.get("asset_type")
        if asset_type:
            qs = qs.filter(asset_type=asset_type)
        return qs

    @extend_schema(
        tags=["clipping-assets"],
        summary="Get a direct URL for the media asset file",
        responses={
            200: inline_serializer(
                name="MediaAssetPreviewUrlResponse",
                fields={"url": drf_serializers.URLField()},
            ),
            404: OpenApiResponse(description="Asset has no file"),
        },
    )
    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMediaAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


@extend_schema_view(
    list=extend_schema(tags=["clipping-assets"], summary="List music assets"),
    create=extend_schema(tags=["clipping-assets"], summary="Upload a music asset"),
    retrieve=extend_schema(tags=["clipping-assets"], summary="Get a music asset"),
    partial_update=extend_schema(tags=["clipping-assets"], summary="Update a music asset"),
    destroy=extend_schema(tags=["clipping-assets"], summary="Delete a music asset"),
)
class ClipMusicAssetViewSet(ModelViewSet):
    queryset = ClipMusicAsset.objects.order_by("genre", "name")
    serializer_class = ClipMusicAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["clipping-assets"],
        summary="Get a direct URL for the music asset file",
        responses={
            200: inline_serializer(
                name="MusicAssetPreviewUrlResponse",
                fields={"url": drf_serializers.URLField()},
            ),
            404: OpenApiResponse(description="Asset has no file"),
        },
    )
    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMusicAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


@extend_schema_view(
    list=extend_schema(tags=["clipping-assets"], summary="List render templates"),
    create=extend_schema(tags=["clipping-assets"], summary="Create a render template"),
    retrieve=extend_schema(tags=["clipping-assets"], summary="Get a render template"),
    partial_update=extend_schema(tags=["clipping-assets"], summary="Update a render template"),
    destroy=extend_schema(tags=["clipping-assets"], summary="Delete a render template (blocked if is_default=True)"),
)
class ClipRenderTemplateViewSet(ModelViewSet):
    queryset = ClipRenderTemplate.objects.order_by("-is_default", "name")
    serializer_class = ClipRenderTemplateSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        template: ClipRenderTemplate = self.get_object()
        if template.is_default:
            return Response(
                {"detail": "Cannot delete the default render template."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        tags=["clipping-assets"],
        summary="Set this template as the default render template",
        request=None,
        responses={200: ClipRenderTemplateSerializer},
    )
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request: Request, pk: str | None = None) -> Response:
        template: ClipRenderTemplate = self.get_object()
        template.is_default = True
        template.save(update_fields=["is_default", "updated_at"])
        return Response(ClipRenderTemplateSerializer(template).data)


@extend_schema_view(
    list=extend_schema(
        tags=["clipping-posts"],
        summary="List clip posts (filter by ?render=)",
        parameters=[
            OpenApiParameter(
                name="render",
                description="Filter by ClipRender UUID",
                required=False,
                type=str,
            ),
        ],
    ),
    retrieve=extend_schema(tags=["clipping-posts"], summary="Get a clip post"),
)
class ClipPostViewSet(ReadOnlyModelViewSet):
    queryset = ClipPost.objects.select_related("render", "social_account")
    serializer_class = ClipPostSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        render_id = self.request.query_params.get("render")
        if render_id:
            qs = qs.filter(render_id=render_id)
        return qs

    @extend_schema(
        tags=["clipping-posts"],
        summary="Queue an analytics sync for this clip post",
        request=None,
        responses={
            200: inline_serializer(
                name="SyncAnalyticsResponse",
                fields={"queued": drf_serializers.BooleanField()},
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="sync-analytics")
    def sync_analytics(self, request: Request, pk: str | None = None) -> Response:
        post: ClipPost = self.get_object()
        sync_clip_analytics.delay(str(post.id))
        return Response({"queued": True})
```

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All **PASS**.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/views/overlays.py ***REMOVED***/clipping/views/assets.py
git commit -m "feat(openapi): annotate overlays, assets, posts viewsets with @extend_schema"
```

---

## Task 10: Schema generation verification

**Files:**
- No code changes — verification only.

- [ ] **Step 1: Start Docker services**

```bash
just up
```

- [ ] **Step 2: Verify the OpenAPI schema generates without errors**

```bash
just manage spectacular --file /tmp/schema.yaml --validate
```

Expected: `Successfully generated schema at /tmp/schema.yaml` with no warnings about missing serializers or ambiguous types.

Alternatively, hit the endpoint directly once Django is running:

```bash
curl -s -o /tmp/schema.json -w "%{http_code}" \
  -H "Authorization: Bearer <your_access_token>" \
  http://localhost:8000/api/schema/
```

Expected: `200`.

- [ ] **Step 3: Verify all expected tags appear in the schema**

```bash
grep -E '"(auth|social-accounts|clipping-jobs|clipping-candidates|clipping-renders|clipping-assets|clipping-overlays|clipping-posts)"' /tmp/schema.yaml | sort -u
```

Expected: All 8 tag strings appear.

- [ ] **Step 4: Run the complete test suite one final time**

```bash
uv run pytest ***REMOVED***/clipping/tests/ ***REMOVED***/channels/tests/ ***REMOVED***/users/ -v
```

Expected: All **PASS**.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat(api): clipping API completion — auth, social-accounts, pagination, OpenAPI"
```
