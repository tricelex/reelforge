# Clipping API Completion — Design Spec

**Date:** 2026-05-02
**Status:** Approved
**Goal:** Complete the clipping backend so it is fully consumable by a Next.js frontend app. No YouTube pipeline work. Focus: auth completeness, social accounts API, pagination, and OpenAPI schema annotations.

---

## Context

The clipping backend (`feat/clipping-backend-v2`) is merged and functional. All core CRUD endpoints, the SSE stream, and the render pipeline with gate support are in place. This spec covers the four gaps identified before handing off to a separate Next.js frontend:

1. Auth block is incomplete — no logout, no user profile endpoint
2. No `SocialAccount` list API (required for the job creation form)
3. List endpoints are unbounded — no pagination
4. OpenAPI schema is auto-generated but inaccurate on custom actions

**Users:** Staff/operators only (`is_staff=True`). The `IsAdminUser` default permission is intentional and stays.

---

## Section 1 — Auth Block

### 1.1 Logout

**Endpoint:** `POST /api/v1/auth/logout/`

- Uses `rest_framework_simplejwt.token_blacklist`
- Add `rest_framework_simplejwt.token_blacklist` to `INSTALLED_APPS` in `config/settings/base.py`
- Run migration (`python manage.py migrate token_blacklist`)
- Add `"BLACKLIST_AFTER_ROTATION": True` to `SIMPLE_JWT` settings so rotated refresh tokens are also auto-blacklisted
- Request body: `{"refresh": "<refresh_token>"}`
- Response: `204 No Content`
- `@extend_schema(tags=["auth"], summary="Logout — blacklist refresh token")`

### 1.2 User Profile

**Endpoint:** `GET /api/v1/auth/me/`

- New `CurrentUserView(RetrieveAPIView)` in `***REMOVED***/users/api/views.py`
- Overrides `get_object()` to return `request.user` directly (no URL kwargs lookup)
- Serializer: `CurrentUserSerializer` — fields: `id`, `email`, `first_name`, `last_name`, `is_staff`, `date_joined`
- Auth: JWT (inherits default `IsAdminUser`)
- The existing `/api/users/me/` on the legacy router is left intact (no breakage)
- `@extend_schema(tags=["auth"], summary="Get current authenticated user")`

### 1.3 CORS

**Settings change (`config/settings/base.py`):**

```python
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
```

**Local env (`.envs/.local/.django`):**

```
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

`CORS_ALLOW_CREDENTIALS = True` is required for Next.js auth patterns that store tokens in `httpOnly` cookies.

---

## Section 2 — Social Accounts API

### 2.1 SocialAccountViewSet

**Endpoints:**
- `GET /api/v1/social-accounts/` — list
- `GET /api/v1/social-accounts/{id}/` — retrieve

**Implementation:**
- `SocialAccountViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet)` — read-only
- Lives in `***REMOVED***/channels/views.py` (new file)
- Registered on the main DRF router: `router.register(r"social-accounts", SocialAccountViewSet, basename="social-account")`

**Serializer (`SocialAccountSerializer`):**

| Field | Notes |
|---|---|
| `id` | UUID |
| `platform` | Raw value: `YOUTUBE`, `TIKTOK`, `INSTAGRAM` |
| `platform_display` | Human label via `get_platform_display()` |
| `handle` | Username/handle on the platform |
| `display_name` | Human-readable name |
| `is_active` | Boolean |
| `channel_id` | FK channel UUID |
| `channel_name` | Channel `__str__` or `name` field (read-only, nested) |

**Filtering:** `?platform=TIKTOK`, `?is_active=true` — frontend uses these when populating the job creation form

**Ordering:** matches `Meta.ordering = ["channel", "platform"]`

**OpenAPI:** `@extend_schema(tags=["social-accounts"])`

---

## Section 3 — Pagination

**Global setting added to `REST_FRAMEWORK` in `config/settings/base.py`:**

```python
"DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
"PAGE_SIZE": 20,
```

**Response envelope (all list endpoints):**

```json
{
  "count": 87,
  "next": "http://localhost:8000/api/v1/clipping/jobs/?page=2",
  "previous": null,
  "results": [...]
}
```

**Exceptions:** The SSE stream (`GET /api/v1/clipping/jobs/{id}/stream/`) returns a `StreamingHttpResponse` — DRF pagination middleware does not apply.

No per-viewset overrides are needed.

---

## Section 4 — OpenAPI Annotations

`drf-spectacular` is already installed. The gap is inaccurate schema on custom `@action` endpoints and non-standard views.

### 4.1 Tag Groups

All viewsets and views are tagged for clean grouping in Swagger UI:

| Tag | Covers |
|---|---|
| `auth` | `token/`, `token/refresh/`, `logout/`, `me/` |
| `social-accounts` | `SocialAccountViewSet` |
| `clipping-jobs` | `ClippingJobViewSet` |
| `clipping-candidates` | `ClipCandidateViewSet`, `ClipLayoutConfigViewSet`, `ClipStyleConfigViewSet` |
| `clipping-renders` | `ClipRenderViewSet` |
| `clipping-assets` | `ClipMediaAssetViewSet`, `ClipMusicAssetViewSet`, `ClipRenderTemplateViewSet` |
| `clipping-overlays` | `ClipTimedOverlayViewSet` |
| `clipping-posts` | `ClipPostViewSet` |

### 4.2 Annotation Targets

Every `@action` decorator on every ViewSet gets `@extend_schema` with:
- `summary` — one-line human description
- `tags` — matches group above
- `request` — inline serializer or `OpenApiTypes` primitive for body
- `responses` — explicit response serializer or status code dict

**Special cases:**
- `GET /api/v1/clipping/jobs/{id}/stream/` — annotated as SSE: `@extend_schema(responses={200: OpenApiTypes.STR}, description="Server-Sent Events stream...")`
- `POST /api/v1/auth/logout/` — `responses={204: None}`
- `GET /api/v1/auth/me/` — `responses={200: CurrentUserSerializer}`

### 4.3 SPECTACULAR_SETTINGS update

Add `ENUM_GENERATE_CHOICE_DESCRIPTION: True` so platform/status choices are documented inline.

### 4.4 Client Generation

The Next.js team can generate a typed API client from the schema:

```bash
npx openapi-typescript http://localhost:8000/api/schema/ -o src/lib/api.d.ts
# or
npx orval --input http://localhost:8000/api/schema/ --output src/lib/api
```

---

## Existing API Surface (for reference)

All of the below already exists and requires no changes:

```
POST   /api/v1/auth/token/
POST   /api/v1/auth/token/refresh/

GET    /api/v1/clipping/jobs/
POST   /api/v1/clipping/jobs/
GET    /api/v1/clipping/jobs/{id}/
PATCH  /api/v1/clipping/jobs/{id}/
DELETE /api/v1/clipping/jobs/{id}/
POST   /api/v1/clipping/jobs/{id}/start-render/
POST   /api/v1/clipping/jobs/{id}/approve-all/
POST   /api/v1/clipping/jobs/{id}/retry/
GET    /api/v1/clipping/jobs/{id}/stream/        ← SSE

GET    /api/v1/clipping/candidates/              ← ?job=, ?status=
GET    /api/v1/clipping/candidates/{id}/
PATCH  /api/v1/clipping/candidates/{id}/
POST   /api/v1/clipping/candidates/{id}/approve/
POST   /api/v1/clipping/candidates/{id}/reject/
POST   /api/v1/clipping/candidates/{id}/undo-reject/
POST   /api/v1/clipping/candidates/{id}/trigger-preview/
GET    /api/v1/clipping/candidates/{id}/preview-status/

GET    /api/v1/clipping/layout-configs/{id}/
PATCH  /api/v1/clipping/layout-configs/{id}/
POST   /api/v1/clipping/layout-configs/{id}/reset-crop/

GET    /api/v1/clipping/style-configs/{id}/
PATCH  /api/v1/clipping/style-configs/{id}/
POST   /api/v1/clipping/style-configs/{id}/apply-template/

GET    /api/v1/clipping/renders/                 ← ?candidate=
GET    /api/v1/clipping/renders/{id}/
POST   /api/v1/clipping/renders/{id}/resume/
POST   /api/v1/clipping/renders/{id}/rerun/{stage_order}/
GET    /api/v1/clipping/renders/{id}/download/

GET    /api/v1/clipping/overlays/                ← ?candidate=
POST   /api/v1/clipping/overlays/
GET    /api/v1/clipping/overlays/{id}/
PATCH  /api/v1/clipping/overlays/{id}/
DELETE /api/v1/clipping/overlays/{id}/

GET    /api/v1/clipping/media-assets/            ← ?asset_type=
POST   /api/v1/clipping/media-assets/
GET    /api/v1/clipping/media-assets/{id}/
PATCH  /api/v1/clipping/media-assets/{id}/
DELETE /api/v1/clipping/media-assets/{id}/
GET    /api/v1/clipping/media-assets/{id}/preview-url/

GET    /api/v1/clipping/music-assets/
POST   /api/v1/clipping/music-assets/
GET    /api/v1/clipping/music-assets/{id}/
PATCH  /api/v1/clipping/music-assets/{id}/
DELETE /api/v1/clipping/music-assets/{id}/
GET    /api/v1/clipping/music-assets/{id}/preview-url/

GET    /api/v1/clipping/render-templates/
POST   /api/v1/clipping/render-templates/
GET    /api/v1/clipping/render-templates/{id}/
PATCH  /api/v1/clipping/render-templates/{id}/
DELETE /api/v1/clipping/render-templates/{id}/
POST   /api/v1/clipping/render-templates/{id}/set-default/

GET    /api/v1/clipping/posts/                   ← ?render=
GET    /api/v1/clipping/posts/{id}/
POST   /api/v1/clipping/posts/{id}/sync-analytics/
```

**New endpoints added by this spec:**

```
POST   /api/v1/auth/logout/
GET    /api/v1/auth/me/
GET    /api/v1/social-accounts/                  ← ?platform=, ?is_active=
GET    /api/v1/social-accounts/{id}/
```

---

## Files Changed / Created

| File | Change |
|---|---|
| `config/settings/base.py` | Add `token_blacklist` to INSTALLED_APPS, add `BLACKLIST_AFTER_ROTATION`, add pagination settings, add `CORS_ALLOWED_ORIGINS` + `CORS_ALLOW_CREDENTIALS`, add `ENUM_GENERATE_CHOICE_DESCRIPTION` |
| `.envs/.local/.django` | Add `CORS_ALLOWED_ORIGINS=http://localhost:3000` |
| `config/urls.py` | Register `SocialAccountViewSet` on router; add `logout/` and `me/` URL paths |
| `***REMOVED***/users/api/views.py` | Add `CurrentUserView` + `CurrentUserSerializer` |
| `***REMOVED***/channels/views.py` | New file — `SocialAccountViewSet` + `SocialAccountSerializer` |
| `***REMOVED***/clipping/views/jobs.py` | Add `@extend_schema` to all actions |
| `***REMOVED***/clipping/views/candidates.py` | Add `@extend_schema` to all actions |
| `***REMOVED***/clipping/views/renders.py` | Add `@extend_schema` to all actions |
| `***REMOVED***/clipping/views/overlays.py` | Add `@extend_schema` to all actions |
| `***REMOVED***/clipping/views/assets.py` | Add `@extend_schema` to all actions |

---

## Out of Scope

- YouTube pipeline endpoints
- User registration / signup via API (users created in admin only)
- Webhook integration
- WebSocket alternative to SSE
- Rate limiting / throttling
- Per-user data isolation (all staff see all data)
