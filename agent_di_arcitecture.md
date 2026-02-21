# Architecture Patterns: Third-Party API Integration, Dependency Injection, and Structured JSON Fields in Django

This document describes a set of architectural patterns for building production-grade Django applications that integrate with third-party APIs (e.g. YouTube Data API, SerpApi), use dependency injection for clean separation of concerns, and enforce schema validation on JSON database fields using Pydantic. These patterns are framework-agnostic in principle but are implemented here specifically for Django + Celery + OpenAI Agents SDK projects.

---

## Table of Contents

1. [Overview and Guiding Principles](#1-overview-and-guiding-principles)
2. [Project Structure](#2-project-structure)
3. [The Service Client Pattern](#3-the-service-client-pattern)
4. [OAuth2 Handling](#4-oauth2-handling)
5. [The Provider Pattern](#5-the-provider-pattern)
6. [Protocol-Based Interfaces](#6-protocol-based-interfaces)
7. [Dependency Injection with dependency-injector](#7-dependency-injection-with-dependency-injector)
8. [Wiring DI into Django](#8-wiring-di-into-django)
9. [Pydantic + Custom JSONField for Structured JSON in Django](#9-pydantic--custom-jsonfield-for-structured-json-in-django)
10. [Exception Hierarchy](#10-exception-hierarchy)
11. [Using the Client Outside the Agent Layer](#11-using-the-client-outside-the-agent-layer)
12. [Testing Strategy](#12-testing-strategy)
13. [Swapping a Provider](#13-swapping-a-provider)
14. [Key Rules and Invariants](#14-key-rules-and-invariants)

---

## 1. Overview and Guiding Principles

### The Core Problem

Naive Django projects often scatter third-party API calls directly inside views, tasks, or agent tools. This creates:

- Tight coupling between business logic and a specific vendor's API
- No way to swap providers without touching every call site
- No clean separation of HTTP concerns, normalization, and consumption
- Global state that is impossible to mock cleanly in tests

### The Solution: Three Distinct Layers

```
Consumer (tool, view, task, admin action)
    └── Provider (normalizes data into internal schemas)
          └── Client (handles HTTP + auth for a specific vendor)
```

Each layer has a single job:

- **Client** — knows how to talk to one specific external API. Handles auth, HTTP errors, retries, pagination. Returns raw or minimally processed data.
- **Provider** — knows how to translate a provider's raw response into your application's internal data schemas. Contains normalization logic. Satisfies a Protocol interface so it is swappable.
- **Consumer** — uses the Provider interface only. Never instantiates HTTP clients. Never knows which vendor is behind the provider.

A **DI container** wires these layers together and manages object lifetimes. Consumers declare what they need; the container supplies it.

### Why Not Client + Adapter (Two Classes)?

The classic "client + adapter" split creates two classes doing one job split across two files. The client fetches raw data; the adapter normalizes it. Since these two concerns are inherently coupled to the same vendor, collapsing them into a single **Provider** class is cleaner. The provider handles both fetching and normalization for one vendor. If you need to swap vendors, you write a new provider — not a new client AND a new adapter.

The one exception is when your HTTP client needs to be used independently of the agent/tool layer (e.g. for admin actions, views, background tasks). In that case, the **service client** lives separately in a `services/` layer, and the **provider** is a thin wrapper that delegates HTTP to the service client and normalizes the result. This is the pattern described in this document.

---

## 2. Project Structure

```
yourapp/
├── services/
│   └── <vendor>/               # e.g. youtube/, stripe/, sendgrid/
│       ├── __init__.py
│       ├── client.py           # Full vendor API client — used anywhere in the project
│       ├── oauth.py            # OAuth2 flow handling (if applicable)
│       └── exceptions.py       # Vendor-specific exception hierarchy
│
├── agents/                     # OR: any consumer layer (views/, workers/, etc.)
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── protocols.py        # Protocol interfaces (structural typing)
│   │   ├── <vendor>.py         # Provider implementation per vendor
│   │   └── <vendor2>.py
│   ├── containers.py           # DI container
│   ├── schemas.py              # Internal shared data schemas (dataclasses + Pydantic)
│   └── tools.py                # Consumers — use providers via DI injection
│
├── models.py                   # Django models — use PydanticField for JSON columns
├── fields.py                   # PydanticField custom field definition
├── admin.py                    # Admin — uses service clients directly
├── tasks.py                    # Celery tasks — uses service clients + agents
└── apps.py                     # AppConfig — wires DI container on startup
```

**Key rule:** The `services/<vendor>/client.py` is a general-purpose class available everywhere in the project. The `agents/providers/<vendor>.py` is only the agents layer's concern. The agents provider delegates to the service client.

---

## 3. The Service Client Pattern

The service client is a plain Python class that encapsulates all HTTP communication with one external API. It is not tied to the agent layer, not tied to any DI container, and can be imported and instantiated anywhere.

### Design Decisions

- **Two operating modes**: API key (public data) and OAuth token (authenticated operations). The same class handles both — the mode is determined at instantiation time.
- **Error normalization**: All HTTP errors are caught and re-raised as your own exception types (never let `httpx.HTTPStatusError` or `requests.exceptions.RequestException` leak into business logic).
- **Token refresh**: The client handles token expiry and refresh internally when operating in OAuth mode. Callers don't need to think about this.
- **`from_credential` classmethod**: A named constructor that accepts a stored credential model instance and initializes the client in OAuth mode.

### Structure

```python
# services/<vendor>/client.py

import httpx
from django.conf import settings
from .exceptions import VendorAPIError, VendorAuthError, VendorQuotaError
from .oauth import refresh_access_token

BASE_URL = "https://api.vendor.com/v1"


class VendorClient:
    """
    Full API client for <Vendor>.

    Two modes:
      - API key mode:  VendorClient()
      - OAuth mode:    VendorClient.from_credential(credential)
    """

    def __init__(
        self,
        api_key: str | None = None,
        access_token: str | None = None,
        credential=None,               # Django model instance storing tokens
    ):
        self.api_key = api_key or settings.VENDOR_API_KEY
        self.access_token = access_token
        self._credential = credential
        self.http = httpx.Client(timeout=15)

    @classmethod
    def from_credential(cls, credential) -> "VendorClient":
        """Initialize an authenticated client from a stored credential model."""
        instance = cls(credential=credential)
        instance._ensure_fresh_token()
        return instance

    # --- Internal helpers ---

    def _ensure_fresh_token(self):
        """Refresh the OAuth access token if it has expired."""
        if not self._credential:
            return
        if self._credential.is_expired:
            token_data = refresh_access_token(self._credential.refresh_token)
            from django.utils import timezone
            from datetime import timedelta
            self._credential.access_token = token_data["access_token"]
            self._credential.token_expiry = timezone.now() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )
            self._credential.save(update_fields=["access_token", "token_expiry"])
        self.access_token = self._credential.access_token

    def _get_headers(self) -> dict:
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    def _build_params(self, params: dict) -> dict:
        """Inject API key for public endpoints when not in OAuth mode."""
        if not self.access_token:
            params["key"] = self.api_key
        return params

    def _get(self, endpoint: str, params: dict) -> dict:
        response = self.http.get(
            f"{BASE_URL}/{endpoint}",
            params=self._build_params(params),
            headers=self._get_headers(),
        )
        self._handle_errors(response)
        return response.json()

    def _handle_errors(self, response: httpx.Response):
        if response.status_code == 200:
            return
        if response.status_code == 401:
            raise VendorAuthError("Invalid or expired credentials.")
        if response.status_code == 403:
            raise VendorAuthError("Access forbidden. Check OAuth scopes.")
        if response.status_code == 429:
            raise VendorQuotaError("Rate limit exceeded.")
        raise VendorAPIError(
            f"API error {response.status_code}: {response.text}",
            status_code=response.status_code,
        )

    def _require_auth(self):
        """Guard for methods that require OAuth. Call at top of any OAuth-only method."""
        if not self.access_token:
            raise VendorAuthError("This method requires OAuth authentication.")

    # --- Public data methods (API key sufficient) ---

    def get_resource(self, resource_id: str) -> dict:
        return self._get("resources", {"id": resource_id})

    # --- Authenticated methods (OAuth required) ---

    def get_my_profile(self) -> dict:
        self._require_auth()
        return self._get("me", {})
```

### Usage

```python
# Anywhere in the project — views, tasks, admin actions, management commands

from yourapp.services.youtube.client import YouTubeClient
from yourapp.models import YouTubeCredential

# Public data — no auth needed
client = YouTubeClient()
trending = client.get_trending_videos(region_code="US")

# Authenticated — pass the stored credential
credential = YouTubeCredential.objects.get(user=request.user)
auth_client = YouTubeClient.from_credential(credential)
stats = auth_client.get_my_channel_stats()
videos = auth_client.get_my_videos()
```

---

## 4. OAuth2 Handling

OAuth logic lives in `services/<vendor>/oauth.py` as standalone functions — not methods on the client. This keeps the client focused on API calls and makes the OAuth flow reusable from views or management commands independently of the client.

```python
# services/<vendor>/oauth.py

import httpx
from datetime import timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.utils import timezone
from .exceptions import VendorAuthError

SCOPES = [
    "https://www.googleapis.com/auth/vendor.readonly",
    "https://www.googleapis.com/auth/vendor.write",
]

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def get_authorization_url(redirect_uri: str, state: str | None = None) -> str:
    """Build the OAuth2 authorization URL to redirect the user to."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",      # force consent to always get a refresh_token
    }
    if state:
        params["state"] = state
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    response = httpx.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    if response.status_code != 200:
        raise VendorAuthError(f"Token exchange failed: {response.text}")
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    """Obtain a new access token using a stored refresh token."""
    response = httpx.post(GOOGLE_TOKEN_URL, data={
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if response.status_code != 200:
        raise VendorAuthError(f"Token refresh failed: {response.text}")
    return response.json()


def save_credentials(user, token_data: dict):
    """Persist OAuth tokens to the database after a successful exchange."""
    from yourapp.models import VendorCredential

    expiry = timezone.now() + timedelta(seconds=token_data.get("expires_in", 3600))
    cred, _ = VendorCredential.objects.update_or_create(
        user=user,
        defaults={
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "token_expiry": expiry,
            "scope": token_data.get("scope", ""),
        },
    )
    return cred
```

### Credential Model

```python
# models.py

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class VendorCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="vendor_credential")
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_expired(self) -> bool:
        if not self.token_expiry:
            return True
        return timezone.now() >= self.token_expiry
```

---

## 5. The Provider Pattern

A provider is a class that:

1. Accepts a service client (or its own HTTP client) in its constructor
2. Calls the client to fetch raw data
3. Normalizes raw responses into your application's internal data schemas
4. Satisfies a Protocol interface (described in section 6)

Providers live in the consumer layer (e.g. `agents/providers/`). They are the boundary between external vendor data and internal application data.

```python
# agents/providers/youtube.py

from yourapp.services.youtube.client import YouTubeClient
from ..schemas import VideoResult


class YouTubeProvider:
    """
    Satisfies the VideoSearchProvider protocol.
    Delegates HTTP to YouTubeClient; normalizes responses into VideoResult.
    """

    def __init__(self, client: YouTubeClient | None = None):
        self._client = client or YouTubeClient()

    def search_videos(self, query: str, max_results: int = 10) -> list[VideoResult]:
        raw = self._client.search_videos(query, max_results)
        return [self._normalize(item) for item in raw]

    def get_trending(self, region_code: str = "US", category_id: str = "0") -> list[VideoResult]:
        raw = self._client.get_trending_videos(region_code, category_id)
        return [self._normalize(item, use_id_direct=True) for item in raw]

    def get_channel_videos(self, channel_id: str, max_results: int = 10) -> list[VideoResult]:
        raw = self._client.get_channel_videos(channel_id, max_results)
        return [self._normalize(item) for item in raw]

    def _normalize(self, item: dict, use_id_direct: bool = False) -> VideoResult:
        video_id = item["id"] if use_id_direct else item["id"]["videoId"]
        stats = item.get("statistics", {})
        return VideoResult(
            title=item["snippet"]["title"],
            url=f"https://youtube.com/watch?v={video_id}",
            channel=item["snippet"]["channelTitle"],
            views=int(stats.get("viewCount", 0) or 0),
            likes=int(stats.get("likeCount", 0) or 0),
            published_at=item["snippet"]["publishedAt"],
        )
```

### Internal Data Schemas

Providers normalize into internal schemas — plain dataclasses for lightweight provider output, Pydantic models for anything that gets validated or stored in the database.

```python
# agents/schemas.py

from dataclasses import dataclass
from pydantic import BaseModel


# --- Provider output schemas (dataclasses — no validation overhead needed) ---

@dataclass
class VideoResult:
    title: str
    url: str
    channel: str
    views: int | None = None
    likes: int | None = None
    published_at: str | None = None


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class SearchReport:
    organic_results: list[SearchResult]
    people_also_ask: list[str]
    related_searches: list[str]


@dataclass
class TrendData:
    keyword: str
    interest_over_time: list[dict]
    related_queries: list[str]


# --- Agent/task output schemas (Pydantic — validated and stored in DB) ---

class ContentAngle(BaseModel):
    angle: str
    rationale: str
    suggested_title: str


class AgentOutputReport(BaseModel):
    summary: str
    content_angles: list[ContentAngle] = []
    content_gaps: list[str] = []
    recommended_angle: ContentAngle | None = None
```

**Rule:** Use `dataclass` for transient data that flows through the system but is never stored. Use `BaseModel` (Pydantic) for data that is validated against a schema, returned from an LLM, or written to a database column.

---

## 6. Protocol-Based Interfaces

Providers satisfy interfaces defined using `typing.Protocol`. This is structural subtyping — a class satisfies a Protocol if it implements the required methods, regardless of inheritance. No `ABC`, no `register()`, no base class needed.

```python
# agents/providers/protocols.py

from typing import Protocol, runtime_checkable
from ..schemas import VideoResult, SearchReport, TrendData


@runtime_checkable
class VideoSearchProvider(Protocol):
    """
    Any class that implements these three methods satisfies this interface.
    No inheritance required.
    """
    def search_videos(self, query: str, max_results: int = 10) -> list[VideoResult]: ...
    def get_trending(self, region_code: str = "US", category_id: str = "0") -> list[VideoResult]: ...
    def get_channel_videos(self, channel_id: str, max_results: int = 10) -> list[VideoResult]: ...


@runtime_checkable
class WebSearchProvider(Protocol):
    def search(self, query: str) -> SearchReport: ...
    def search_youtube(self, query: str) -> list[VideoResult]: ...
    def get_trends(self, keyword: str, region: str = "US") -> TrendData: ...
```

### Why Protocol over ABC

| | `ABC` | `Protocol` |
|---|---|---|
| Requires inheritance | Yes | No |
| Works with third-party classes | No | Yes |
| Supports `isinstance()` checks | Yes | Yes (with `@runtime_checkable`) |
| Enforces at type-check time | Yes | Yes (via mypy/pyright) |
| Decouples interface from implementation | No | Yes |

With `Protocol`, if you get a provider from an external library that happens to implement `search_videos`, `get_trending`, and `get_channel_videos`, it satisfies `VideoSearchProvider` without any modification. This is not possible with ABC.

---

## 7. Dependency Injection with dependency-injector

Install: `pip install dependency-injector`

The DI container wires providers and clients together, manages their lifetimes (`Singleton` = one instance per container), and makes dependencies injectable into any function or class via `@inject` + `Provide[...]`.

```python
# agents/containers.py

from dependency_injector import containers, providers
from .providers.youtube import YouTubeProvider
from .providers.serpapi import SerpApiProvider
from yourapp.services.youtube.client import YouTubeClient


class AgentContainer(containers.DeclarativeContainer):
    """
    Wiring configuration for all agent-layer dependencies.

    Swap any provider by changing the Singleton here.
    Nothing in consumers (tools, views) changes when you do.

    Example swap:
        web_search = providers.Singleton(BraveSearchProvider, api_key=config.brave_api_key)
    """

    config = providers.Configuration()

    # Service clients
    youtube_client = providers.Singleton(
        YouTubeClient,
        api_key=config.youtube_api_key,
    )

    # Providers — what consumers depend on
    video_search = providers.Singleton(
        YouTubeProvider,
        client=youtube_client,
    )

    web_search = providers.Singleton(
        SerpApiProvider,
        api_key=config.serpapi_key,
    )
```

### Provider Lifetimes

`dependency_injector` supports several lifetime scopes:

- `providers.Singleton` — one instance per container. Reused across all calls. Use for stateless clients and providers.
- `providers.Factory` — new instance on every call. Use when you need fresh state per request.
- `providers.ThreadLocalSingleton` — one instance per thread. Use if your client holds thread-local state.

In most cases, `Singleton` is correct for API clients and providers because they are stateless (auth tokens are refreshed in-place).

### Injecting Dependencies into Functions

```python
# agents/tools.py

from dependency_injector.wiring import inject, Provide
from .containers import AgentContainer
from .providers.protocols import VideoSearchProvider


@inject
def search_videos_tool(
    query: str,
    max_results: int = 10,
    provider: VideoSearchProvider = Provide[AgentContainer.video_search],
) -> list[dict]:
    results = provider.search_videos(query, max_results)
    return [r.__dict__ for r in results]
```

The `provider` parameter is automatically injected by the DI framework at call time. You never pass it manually in production code. In tests, you override the container binding instead.

### Injecting into Classes

```python
from dependency_injector.wiring import inject, Provide


class SomeService:
    @inject
    def __init__(
        self,
        video_provider: VideoSearchProvider = Provide[AgentContainer.video_search],
    ):
        self.video_provider = video_provider
```

---

## 8. Wiring DI into Django

The container must be initialized and wired before any module that uses `@inject` is imported and called. The correct place is `AppConfig.ready()`.

```python
# apps.py

from django.apps import AppConfig
from django.conf import settings


class YourAppConfig(AppConfig):
    name = "yourapp"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from .agents.containers import AgentContainer

        container = AgentContainer()

        # Load config from Django settings
        container.config.from_dict({
            "youtube_api_key": settings.YOUTUBE_API_KEY,
            "serpapi_key": settings.SERPAPI_KEY,
        })

        # Wire the container to all modules that use @inject
        # List every module that has @inject-decorated functions
        container.wire(modules=[
            "yourapp.agents.tools",
            # "yourapp.views",        # add if views use @inject
            # "yourapp.tasks",        # add if tasks use @inject
        ])

        # Optional: expose container for programmatic access in tests
        YourAppConfig.container = container
```

```python
# settings.py — ensure AppConfig is default
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# yourapp/__init__.py
default_app_config = "yourapp.apps.YourAppConfig"
```

**Important:** `container.wire(modules=[...])` must list every module containing `@inject` decorators. Missing a module means injection silently fails — the default value is used instead of the container binding. This is a common source of bugs.

---

## 9. Pydantic + Custom JSONField for Structured JSON in Django

Django's `JSONField` stores arbitrary JSON with no schema enforcement. At the Python level, it always returns a plain `dict`. The `PydanticField` pattern wraps `JSONField` to automatically validate incoming data against a Pydantic schema and return a Pydantic model instance instead of a dict.

### PydanticField Implementation

```python
# fields.py

from typing import Type, TypeVar
from django.db import models
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class PydanticField(models.JSONField):
    """
    A JSONField that validates data against a Pydantic model schema.

    Behavior:
      - Reading from DB   → returns a Pydantic model instance (not a dict)
      - Writing to DB     → accepts a Pydantic instance and serializes to JSON automatically
      - ORM filtering     → still works (it is a JSONField under the hood)
      - Django admin      → displays raw JSON (readonly fields recommended)
      - Migrations        → handled correctly via deconstruct()

    Usage:
        class MyModel(models.Model):
            data = PydanticField(schema=MyPydanticSchema)

        instance = MyModel.objects.get(pk=1)
        instance.data           # returns MyPydanticSchema instance
        instance.data.field     # fully typed access
    """

    def __init__(self, schema: Type[T], *args, **kwargs):
        self.schema = schema
        kwargs.setdefault("null", True)
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        """Required for Django migrations to reconstruct this field."""
        name, path, args, kwargs = super().deconstruct()
        kwargs["schema"] = self.schema
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        """Called every time a value is read from the database."""
        value = super().from_db_value(value, expression, connection)
        if value is None:
            return None
        if isinstance(value, dict):
            return self.schema.model_validate(value)
        return value

    def to_python(self, value):
        """Called during deserialization and form validation."""
        value = super().to_python(value)
        if value is None:
            return None
        if isinstance(value, dict):
            return self.schema.model_validate(value)
        if isinstance(value, self.schema):
            return value
        return value

    def get_prep_value(self, value):
        """Called before writing to the database."""
        if isinstance(value, BaseModel):
            value = value.model_dump()
        return super().get_prep_value(value)
```

### Defining Schemas

```python
# schemas.py (or inline in models.py)

from pydantic import BaseModel


class NestedItem(BaseModel):
    name: str
    score: float
    tags: list[str] = []


class MyOutputReport(BaseModel):
    summary: str
    items: list[NestedItem] = []
    recommended: NestedItem | None = None
    metadata: dict = {}
```

### Using PydanticField in Models

```python
# models.py

from django.db import models
from .fields import PydanticField
from .schemas import MyOutputReport


class MyJob(models.Model):
    topic = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default="pending")

    # This field stores JSON in the DB but returns MyOutputReport on read
    output_report = PydanticField(schema=MyOutputReport)

    created_at = models.DateTimeField(auto_now_add=True)
```

### Reading and Writing

```python
# Writing — assign a Pydantic instance directly
job = MyJob.objects.get(pk=1)
job.output_report = MyOutputReport(
    summary="Overview of the topic",
    items=[NestedItem(name="Item A", score=9.2, tags=["trending"])],
)
job.save()

# Reading — returns a MyOutputReport instance, fully typed
job = MyJob.objects.get(pk=1)
report = job.output_report          # MyOutputReport
print(report.summary)               # str
print(report.items[0].name)         # str, from NestedItem

# ORM filtering still works (JSONField behavior preserved)
MyJob.objects.filter(output_report__summary__icontains="finance")
```

### Validating LLM Output Before Saving

When the data is produced by an LLM (e.g. an agent that returns JSON), validate it explicitly before assigning to the field:

```python
import json
from pydantic import ValidationError

raw_output = result.final_output  # string from agent

try:
    report = MyOutputReport.model_validate_json(raw_output)
except ValidationError as e:
    # Log the error, mark job as failed, etc.
    raise

job.output_report = report  # safe to assign — already validated
job.save()
```

### Why Not MessagePack or Other Binary Formats

MessagePack is a binary serialization format — it reduces payload size but provides **no schema validation**. Storing as binary in a `BinaryField` sacrifices:

- Django ORM queryability (`filter(field__key=value)` stops working)
- Django admin readability
- Direct SQL inspection

The correct trade-off for most applications is Pydantic + JSONField: you get schema validation, type safety at the Python level, ORM queryability, and human-readable database storage.

---

## 10. Exception Hierarchy

Every external service should have its own exception hierarchy rooted at a base exception. This allows callers to catch broadly (`VendorClientError`) or specifically (`VendorQuotaError`) depending on context.

```python
# services/<vendor>/exceptions.py


class VendorClientError(Exception):
    """Base exception for all <Vendor> client errors."""


class VendorAuthError(VendorClientError):
    """OAuth failure, invalid token, or insufficient scope."""


class VendorQuotaError(VendorClientError):
    """API rate limit or quota exceeded."""


class VendorAPIError(VendorClientError):
    """General API error (non-auth, non-quota)."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)
```

Callers handle exceptions at the appropriate level:

```python
try:
    data = client.get_resource(resource_id)
except VendorQuotaError:
    # Specific handling — back off, notify, etc.
    ...
except VendorAuthError:
    # Specific handling — redirect to re-auth, etc.
    ...
except VendorClientError as e:
    # Broad catch-all for any vendor error
    logger.error(f"Vendor error: {e}")
```

**Rule:** Never let `httpx`, `requests`, or any HTTP library exception propagate beyond the client. Catch them all inside `_handle_errors()` and re-raise as your own types.

---

## 11. Using the Client Outside the Agent Layer

Because the service client is a plain Python class in `services/`, it can be used anywhere in the Django project without involving the DI container or providers. The DI container and providers are exclusively the agent/consumer layer's concern.

### In a Celery Task

```python
# tasks.py

from yourapp.services.youtube.client import YouTubeClient
from yourapp.services.youtube.exceptions import YouTubeQuotaError


@shared_task(bind=True, max_retries=3)
def sync_channel_task(self, channel_id: str):
    client = YouTubeClient()
    try:
        stats = client.get_channel_stats(channel_id)
        Channel.objects.filter(channel_id=channel_id).update(**stats)
    except YouTubeQuotaError:
        raise self.retry(countdown=3600)   # retry in an hour
```

### In a Django Admin Action

```python
# admin.py

from yourapp.services.youtube.client import YouTubeClient
from yourapp.services.youtube.exceptions import YouTubeAuthError, YouTubeQuotaError
from yourapp.models import VendorCredential


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    actions = ["sync_stats"]

    @admin.action(description="Sync channel stats from YouTube")
    def sync_stats(self, request, queryset):
        client = YouTubeClient()   # Public API key — no auth needed for public channels

        for channel in queryset:
            try:
                data = client.get_channel_stats(channel.channel_id)
                channel.subscriber_count = data["subscriber_count"]
                channel.save(update_fields=["subscriber_count"])
            except YouTubeQuotaError:
                self.message_user(request, "Quota exceeded.", messages.ERROR)
                return
            except Exception as e:
                self.message_user(request, f"Failed: {e}", messages.ERROR)

    @admin.action(description="Sync authenticated user's own channel")
    def sync_my_channel(self, request, queryset):
        try:
            credential = request.user.vendor_credential
        except VendorCredential.DoesNotExist:
            self.message_user(request, "No connected account.", messages.ERROR)
            return

        # OAuth mode — from_credential handles token refresh automatically
        client = YouTubeClient.from_credential(credential)
        stats = client.get_my_channel_stats()
        # ... update model
```

### In a Django View

```python
# views.py

from django.http import JsonResponse
from yourapp.services.youtube.client import YouTubeClient


def channel_stats_view(request, channel_id):
    client = YouTubeClient()
    stats = client.get_channel_stats(channel_id)
    return JsonResponse(stats)
```

---

## 12. Testing Strategy

### Testing Providers (no HTTP)

Override the container binding in tests. No patching, no monkeypatching, no `unittest.mock.patch`.

```python
# tests/test_tools.py

from unittest.mock import MagicMock
from yourapp.agents.containers import AgentContainer
from yourapp.agents.schemas import VideoResult


def test_search_videos_tool():
    mock_provider = MagicMock()
    mock_provider.search_videos.return_value = [
        VideoResult(title="Test Video", url="https://youtube.com/watch?v=abc", channel="Test Channel")
    ]

    with AgentContainer.video_search.override(mock_provider):
        from yourapp.agents.tools import search_videos_tool
        result = search_videos_tool("test query")

    mock_provider.search_videos.assert_called_once_with("test query", 10)
    assert "Test Video" in result
```

### Testing the Service Client (mock HTTP)

Use `httpx.MockTransport` or `respx` to mock HTTP without touching the network.

```python
import httpx
import respx
from yourapp.services.youtube.client import YouTubeClient


@respx.mock
def test_get_channel_stats():
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json={
            "items": [{
                "id": "UC123",
                "snippet": {"title": "My Channel", "publishedAt": "2020-01-01T00:00:00Z"},
                "statistics": {"subscriberCount": "1000", "viewCount": "50000", "videoCount": "42"},
            }]
        })
    )

    client = YouTubeClient(api_key="test-key")
    stats = client.get_channel_stats("UC123")

    assert stats["title"] == "My Channel"
    assert stats["subscriber_count"] == 1000
```

### Testing PydanticField

```python
from yourapp.models import MyJob
from yourapp.schemas import MyOutputReport


def test_pydantic_field_roundtrip(db):
    report = MyOutputReport(summary="Test summary")
    job = MyJob.objects.create(topic="test", output_report=report)

    job.refresh_from_db()
    assert isinstance(job.output_report, MyOutputReport)
    assert job.output_report.summary == "Test summary"
```

---

## 13. Swapping a Provider

To swap a provider (e.g. replace SerpApi with Brave Search for web search):

**Step 1:** Write the new provider implementing the same Protocol interface.

```python
# agents/providers/brave.py

import httpx
from django.conf import settings
from ..schemas import SearchReport, SearchResult, VideoResult, TrendData


class BraveSearchProvider:
    """Satisfies WebSearchProvider protocol using Brave Search API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.BRAVE_API_KEY
        self.http = httpx.Client(timeout=15)

    def search(self, query: str) -> SearchReport:
        response = self.http.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query},
            headers={"X-Subscription-Token": self.api_key},
        )
        response.raise_for_status()
        raw = response.json()
        return SearchReport(
            organic_results=[
                SearchResult(title=r["title"], url=r["url"], snippet=r.get("description", ""))
                for r in raw.get("web", {}).get("results", [])[:5]
            ],
            people_also_ask=[],
            related_searches=[],
        )

    def search_youtube(self, query: str) -> list[VideoResult]:
        # Brave doesn't have a YouTube SERP endpoint — return empty or use a different strategy
        return []

    def get_trends(self, keyword: str, region: str = "US") -> TrendData:
        # Brave doesn't have trends — implement or raise NotImplementedError
        return TrendData(keyword=keyword, interest_over_time=[], related_queries=[])
```

**Step 2:** Change one line in the container.

```python
# agents/containers.py

from .providers.brave import BraveSearchProvider   # swap import

class AgentContainer(containers.DeclarativeContainer):
    ...
    web_search = providers.Singleton(
        BraveSearchProvider,                        # swap provider
        api_key=config.brave_api_key,
    )
```

No changes to tools, no changes to tasks, no changes to any consumer. The Protocol ensures compile-time and runtime compatibility.

---

## 14. Key Rules and Invariants

These rules should be followed consistently throughout a codebase using these patterns.

**Client rules:**
- The service client is a plain Python class. It lives in `services/`. It has no knowledge of agents, providers, or DI.
- The client never lets external HTTP library exceptions escape. All errors are caught and re-raised as the project's own exception types.
- The client handles token refresh internally in OAuth mode. Callers should not need to think about token expiry.
- Use `@classmethod from_credential(cls, credential)` as the named constructor for OAuth mode.

**Provider rules:**
- Providers never instantiate HTTP clients themselves — they receive a service client in their constructor.
- Provider methods always return internal schema types (dataclasses or Pydantic models), never raw dicts.
- Providers never raise HTTP library exceptions — these are already normalized by the service client.
- A provider class satisfies a Protocol by having the right methods — no inheritance needed.

**DI container rules:**
- The container is initialized once in `AppConfig.ready()`. Never initialize it elsewhere.
- All modules using `@inject` must be listed in `container.wire(modules=[...])`.
- Use `providers.Singleton` for stateless clients and providers (the common case).
- In tests, use `container.override()` context managers — never use `unittest.mock.patch` on injected dependencies.

**PydanticField rules:**
- Use `PydanticField` for any Django model JSON column that has a known schema.
- Always assign a Pydantic model instance to the field — not a dict — when writing.
- When writing LLM output, always validate with `Schema.model_validate_json(raw_string)` before assigning.
- Keep schemas in a dedicated `schemas.py` — do not define them inline in `models.py`.
- Use `dataclass` for transient in-memory data, `BaseModel` for data that is validated, stored, or returned from an LLM.

**Exception rules:**
- Every external service gets its own exception hierarchy rooted at a `<Service>ClientError` base.
- Catch `<Service>QuotaError` specifically in tasks and implement retry logic.
- Catch `<Service>AuthError` specifically in views and redirect to re-authorization.
- Never catch bare `Exception` in production code unless you immediately log and re-raise.

**General rules:**
- Consumers (tools, views, tasks, admin actions) depend on the Provider Protocol, never on a concrete provider class.
- The service client is the one thing that IS used directly by consumers outside the agent layer (admin actions, views, tasks). This is intentional — the DI container is an agent-layer concern.
- Tool return values (for OpenAI Agents SDK) must always be strings — serialize dataclasses with `json.dumps([r.__dict__ for r in results], default=str)`.
- Keep tool outputs concise. The agent accumulates context across all tool calls — large outputs fill the context window quickly.
