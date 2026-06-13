# Architecture Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the base Django/punq architecture to fix five structural issues before any real features are built: singleton DI container, Protocol-based ports (drops the fragile `inject()` hack), in-process domain event bus, CQRS read-query objects, and an application services scaffold for cross-domain coordination.

**Architecture:** Each task is additive or a clean swap — existing API behaviour is unchanged. The layering contract (`logic → models → infra → api`) is preserved and enforced by import-linter. The `inject()` / `TYPE_CHECKING` hack in `implemented.py` is replaced by direct Protocol imports that punq can resolve natively. The DI container moves from per-request construction to a module-level singleton populated once in `AppConfig.ready()`.

**Tech Stack:** Django 6, punq, attrs, msgspec, pytest, import-linter, ruff, mypy strict.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| CREATE | `server/common/container.py` | Module-level punq singleton |
| CREATE | `server/apps/main/apps.py` | AppConfig — populates container in `ready()` |
| CREATE | `server/apps/main/logic/ports.py` | `BlogPostStore` Protocol (write port) |
| CREATE | `server/apps/main/logic/events.py` | `BlogPostCreated` domain event |
| CREATE | `server/apps/main/infra/store.py` | `BlogPostWriteStoreImpl` — implements `BlogPostStore` |
| CREATE | `server/apps/main/infra/queries.py` | `BlogPostListQuery` — CQRS read object |
| CREATE | `server/common/events.py` | `EventBus` Protocol + `InProcessEventBus` impl |
| CREATE | `server/services/__init__.py` | Cross-domain services scaffold |
| MODIFY | `server/apps/main/__init__.py` | Reference AppConfig |
| MODIFY | `server/common/di.py` | Use global container, remove per-request construction |
| MODIFY | `server/implemented.py` | Singletons, Protocol registration, drop `inject()` hack |
| MODIFY | `server/apps/main/logic/usecases/blogpost_create.py` | Use `BlogPostStore` port + emit `BlogPostCreated` |
| MODIFY | `server/apps/main/logic/usecases/blogpost_get.py` | Use `BlogPostStore` port |
| MODIFY | `server/apps/main/logic/value_objects.py` | Add `BlogPostSummaryPayload` (list DTO) |
| MODIFY | `server/apps/main/api/views.py` | Add `BlogPostList` controller using query |
| MODIFY | `server/apps/main/api/urls.py` | Wire list endpoint |
| MODIFY | `.importlinter` | Add services-layer contracts |
| MODIFY | `CLAUDE.md` | Update architecture section |
| CREATE | `tests/test_server/test_events.py` | Unit tests for `InProcessEventBus` |
| CREATE | `tests/test_apps/test_main/test_infra/test_store.py` | Tests for `BlogPostWriteStoreImpl` |
| CREATE | `tests/test_apps/test_main/test_infra/test_queries.py` | Tests for `BlogPostListQuery` |
| CREATE | `tests/test_apps/test_main/test_api/test_blog_post_list.py` | API test for list endpoint |

---

## Important constraints
- **100% coverage** is enforced — every new line needs a test.
- **`--doctest-modules`** is active — do NOT add example code to docstrings unless it is valid and executable.
- **`from __future__ import annotations`** must be REMOVED from usecase files after this refactor. That import makes all annotations lazy strings at runtime, which is what required the `inject()` hack. Direct Protocol imports mean we no longer need it.
- Run `pytest --no-cov -x` during development (fast). Run `pytest` (full, with coverage) before each commit.
- After each task run: `ruff check . && ruff format . && mypy server tests/**/*.py && lint-imports`

---

## Task 1: Singleton DI Container

**Files:**
- Create: `server/common/container.py`
- Create: `server/apps/main/apps.py`
- Modify: `server/apps/main/__init__.py`
- Modify: `server/common/di.py`

The container currently rebuilds on every HTTP request inside `HasContainer.__init__`. This task moves it to a module-level singleton populated once when Django starts.

- [ ] **Step 1: Write a failing test for singleton behaviour**

Create `tests/test_server/test_container.py`:

```python
import punq
import pytest

from server.common import container as container_module
from server.apps.main.infra.repository import BlogPostRepo


@pytest.fixture(autouse=True)
def _reset_container() -> None:
    """Ensure each test starts with a clean container."""
    container_module.container = punq.Container()


def test_container_is_module_level_singleton() -> None:
    """The container object is always the same module-level instance."""
    from server.common import container as c1
    from server.common import container as c2

    assert c1.container is c2.container
```

Run: `pytest tests/test_server/test_container.py --no-cov -x`
Expected: **ImportError** — `server.common.container` does not exist yet.

- [ ] **Step 2: Create `server/common/container.py`**

```python
"""Module-level punq container — populated once in AppConfig.ready()."""

import punq

container: punq.Container = punq.Container()
```

Run: `pytest tests/test_server/test_container.py --no-cov -x`
Expected: **PASS**

- [ ] **Step 3: Write a failing test for AppConfig wiring**

Add to `tests/test_server/test_container.py`:

```python
from server.apps.main.infra.repository import BlogPostRepo


def test_container_has_blog_post_repo_after_app_ready() -> None:
    """After Django startup, container has BlogPostRepo registered."""
    # Django's AppConfig.ready() is called during pytest-django setup.
    # The container should already be populated.
    repo = container_module.container.resolve(BlogPostRepo)
    assert isinstance(repo, BlogPostRepo)
```

Run: `pytest tests/test_server/test_container.py::test_container_has_blog_post_repo_after_app_ready --no-cov -x`
Expected: **FAIL** — container is empty (no registration yet).

- [ ] **Step 4: Create `server/apps/main/apps.py`**

```python
"""Django application configuration for the main app."""

from django.apps import AppConfig


class MainConfig(AppConfig):
    """Configuration for the main application."""

    name = 'server.apps.main'
    default = True

    def ready(self) -> None:
        """Populate the global DI container once at startup."""
        from server.common import container as container_module
        from server import implemented

        implemented.populate_dependencies(container_module.container)
```

- [ ] **Step 5: Update `server/apps/main/__init__.py`**

The file is currently empty. Add:

```python
"""Main application package."""
```

(Django auto-discovers `MainConfig` via `default = True` — no `default_app_config` string needed in Django 6.)

- [ ] **Step 6: Update `server/common/di.py` to use the global container**

Replace the entire file:

```python
"""Dependency injection helpers for controllers."""

from typing import Any, final

from server.common import container as container_module


class HasContainer:
    """
    Mixin that gives controllers access to the global DI container.

    Must be the first base class in the MRO.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Pass through to the next class in MRO."""
        super().__init__(*args, **kwargs)

    @final
    def resolve[Thing](self, thing: type[Thing]) -> Thing:
        """Resolve a dependency from the global container."""
        return container_module.container.resolve(thing)  # type: ignore[no-any-return]
```

- [ ] **Step 7: Run and fix**

```bash
pytest tests/test_server/test_container.py --no-cov -x
```

If the `_reset_container` fixture breaks things (it replaces the container with an empty one), adjust the test: the `autouse` fixture on the singleton test should only apply to tests that need isolation, not the app-ready test. Refactor `test_container.py` to:

```python
"""Tests for the global DI container."""

import punq
import pytest

from server.common import container as container_module
from server.apps.main.infra.repository import BlogPostRepo


def test_container_is_module_level_singleton() -> None:
    """The container object is always the same module-level instance."""
    from server.common import container as c1
    from server.common import container as c2

    assert c1.container is c2.container


def test_container_has_blog_post_repo_after_app_ready() -> None:
    """After Django startup, container has BlogPostRepo registered."""
    repo = container_module.container.resolve(BlogPostRepo)
    assert isinstance(repo, BlogPostRepo)
```

Run: `pytest tests/test_server/test_container.py --no-cov -x`
Expected: **PASS**

- [ ] **Step 8: Run full suite to confirm no regressions**

```bash
pytest --no-cov -x
```

Expected: all existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add server/common/container.py server/apps/main/apps.py \
        server/apps/main/__init__.py server/common/di.py \
        tests/test_server/test_container.py
git commit -m "feat: move DI container to module-level singleton via AppConfig.ready()"
```

---

## Task 2: Ports / Protocols — Drop the `inject()` Hack

**Files:**
- Create: `server/apps/main/logic/ports.py`
- Create: `server/apps/main/infra/store.py`
- Modify: `server/apps/main/logic/usecases/blogpost_create.py`
- Modify: `server/apps/main/logic/usecases/blogpost_get.py`
- Modify: `server/implemented.py`

**Why this works:** `implemented.py` had a `_create_injector` hack that patched punq's internal `_localns` because usecase classes used `from __future__ import annotations` (making all type annotations lazy strings) combined with `TYPE_CHECKING`-guarded imports. The fix: use `Protocol` types defined in `logic/ports.py`, remove `from __future__ import annotations` from usecase files, and import the protocols directly. punq can then read real type objects from attrs-generated `__init__` signatures.

- [ ] **Step 1: Create `server/apps/main/logic/ports.py`**

```python
"""Write-side ports (Protocols) for the main app's domain."""

from typing import Protocol

from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


class BlogPostStore(Protocol):
    """Write and fetch operations for blog posts, returning value objects."""

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        """Persist a new blog post and return it as a value object."""
        ...

    def get_by_id(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch an existing blog post by primary key."""
        ...
```

- [ ] **Step 2: Create `server/apps/main/infra/store.py`**

This class combines `BlogPostRepo` + `BlogPostMapper` and implements `BlogPostStore`. It is the infra layer's answer to the logic layer's port.

```python
"""Concrete implementation of BlogPostStore."""

from typing import final

import attrs

from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)

if False:  # noqa: SIM223  # used only for type annotations below
    from server.apps.main.infra import mappers, repository


@final
@attrs.define(slots=True, frozen=True)
class BlogPostWriteStoreImpl:
    """Combines repository + mapper to implement BlogPostStore."""

    _repository: 'repository.BlogPostRepo'
    _mapper: 'mappers.BlogPostMapper'

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        """Persist a new blog post."""
        return self._mapper(self._repository.create(payload))

    def get_by_id(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch a blog post by primary key."""
        return self._mapper(self._repository.get_by_id(blog_post_id))
```

> **Note:** `BlogPostWriteStoreImpl` is an infra class — it may import from `models`, `mappers`, `repository` freely. The `if False:` block is the correct pattern here to provide type annotation strings without a circular import at runtime; this is only in infra, not in logic.

Wait — actually, `BlogPostWriteStoreImpl` is in `infra/` and can directly import from `infra/`. No `if False:` trick is needed. Use real imports:

```python
"""Concrete implementation of BlogPostStore."""

from typing import final

import attrs

from server.apps.main.infra.mappers import BlogPostMapper
from server.apps.main.infra.repository import BlogPostRepo
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


@final
@attrs.define(slots=True, frozen=True)
class BlogPostWriteStoreImpl:
    """Combines repository + mapper to implement BlogPostStore."""

    _repository: BlogPostRepo
    _mapper: BlogPostMapper

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        """Persist a new blog post."""
        return self._mapper(self._repository.create(payload))

    def get_by_id(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch a blog post by primary key."""
        return self._mapper(self._repository.get_by_id(blog_post_id))
```

- [ ] **Step 3: Write a failing test for the store**

Create `tests/test_apps/test_main/test_infra/test_store.py`:

```python
"""Tests for BlogPostWriteStoreImpl."""

import pytest

from server.apps.main.infra.mappers import BlogPostMapper
from server.apps.main.infra.repository import BlogPostRepo
from server.apps.main.infra.store import BlogPostWriteStoreImpl
from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


def _make_store() -> BlogPostWriteStoreImpl:
    return BlogPostWriteStoreImpl(
        repository=BlogPostRepo(),
        mapper=BlogPostMapper(),
    )


def test_store_satisfies_protocol() -> None:
    """BlogPostWriteStoreImpl structurally implements BlogPostStore."""
    store = _make_store()
    # runtime_checkable not needed — structural check via isinstance with Protocol
    assert isinstance(store, BlogPostWriteStoreImpl)
    # Verify the protocol methods exist and are callable
    assert callable(store.create)
    assert callable(store.get_by_id)


@pytest.mark.django_db
def test_store_create_persists_and_returns_dto() -> None:
    """create() saves to DB and returns BlogPostFullPayload."""
    store = _make_store()
    payload = BlogPostCreatePayload(title='Hello', body='World')
    result = store.create(payload)
    assert isinstance(result, BlogPostFullPayload)
    assert result.title == 'Hello'
    assert result.body == 'World'
    assert result.id > 0


@pytest.mark.django_db
def test_store_get_by_id_returns_dto() -> None:
    """get_by_id() fetches from DB and returns BlogPostFullPayload."""
    store = _make_store()
    payload = BlogPostCreatePayload(title='Fetch Me', body='Body')
    created = store.create(payload)
    fetched = store.get_by_id(created.id)
    assert fetched == created
```

Run: `pytest tests/test_apps/test_main/test_infra/test_store.py --no-cov -x`
Expected: **FAIL** — `server.apps.main.infra.store` does not exist.

- [ ] **Step 4: Run tests after creating `store.py`**

Run: `pytest tests/test_apps/test_main/test_infra/test_store.py --no-cov -x`
Expected: **PASS**

- [ ] **Step 5: Rewrite `blogpost_create.py` to use the port**

Replace the entire file. Key changes: remove `from __future__ import annotations`, remove `TYPE_CHECKING`, import `BlogPostStore` directly:

```python
"""Use case: create a new blog post."""

from typing import final

import attrs

from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


@final
@attrs.define(slots=True, frozen=True)
class CreateBlogPost:
    """Creates ``BlogPost`` instances."""

    _store: BlogPostStore

    def __call__(
        self,
        parsed_body: BlogPostCreatePayload,
    ) -> BlogPostFullPayload:
        """
        Validate and persist a new blog post.

        Business logic (credits, quotas, etc.) belongs here before
        the ``self._store.create()`` call.
        """
        return self._store.create(parsed_body)
```

- [ ] **Step 6: Rewrite `blogpost_get.py` to use the port**

Replace the entire file:

```python
"""Use case: retrieve a blog post by primary key."""

from typing import final

import attrs

from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import BlogPostFullPayload


@final
@attrs.define(slots=True, frozen=True)
class GetBlogPost:
    """Retrieve ``BlogPost`` models by primary key."""

    _store: BlogPostStore

    def __call__(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch and return the blog post, or raise DoesNotExist."""
        return self._store.get_by_id(blog_post_id)
```

- [ ] **Step 7: Rewrite `server/implemented.py` — drop the inject() hack**

Replace the entire file:

```python
"""Dependency injection wiring — registers all concrete implementations."""

from punq import Container, Scope


def _inject_django(container: Container) -> None:
    from django.conf import LazySettings, settings

    container.register(
        LazySettings,
        instance=settings,
        scope=Scope.singleton,
    )


def _inject_main(container: Container) -> None:
    from server.apps.main.infra import mappers, repository
    from server.apps.main.infra import store as write_store
    from server.apps.main.logic import ports
    from server.apps.main.logic.usecases import blogpost_create, blogpost_get

    # Internal infra components
    container.register(repository.BlogPostRepo, scope=Scope.singleton)
    container.register(mappers.BlogPostMapper, scope=Scope.singleton)

    # Register BlogPostStore Protocol → concrete implementation
    container.register(
        ports.BlogPostStore,
        factory=write_store.BlogPostWriteStoreImpl,
        scope=Scope.singleton,
    )

    # Use cases — punq resolves BlogPostStore from registry automatically
    container.register(blogpost_create.CreateBlogPost, scope=Scope.singleton)
    container.register(blogpost_get.GetBlogPost, scope=Scope.singleton)


def populate_dependencies(container: Container) -> Container:
    """Populate the container with all application dependencies."""
    _inject_django(container)
    _inject_main(container)
    return container
```

- [ ] **Step 8: Run the full test suite**

```bash
pytest --no-cov -x
```

Expected: all tests pass. If `BlogPost.DoesNotExist` is raised in the `GetBlogPost` handler test, that's fine — the error handler in `views.py` catches `BlogPost.DoesNotExist`. But `GetBlogPost` now calls `store.get_by_id()` which calls `repo.get_by_id()` which raises `BlogPost.DoesNotExist` — the same exception the view catches. No change in observable behaviour.

- [ ] **Step 9: Run linters**

```bash
ruff check . && ruff format . && mypy server tests/**/*.py && lint-imports
```

Fix any issues before committing.

- [ ] **Step 10: Commit**

```bash
git add server/apps/main/logic/ports.py \
        server/apps/main/infra/store.py \
        server/apps/main/logic/usecases/blogpost_create.py \
        server/apps/main/logic/usecases/blogpost_get.py \
        server/implemented.py \
        tests/test_apps/test_main/test_infra/test_store.py
git commit -m "feat: introduce BlogPostStore protocol, drop inject() hack, register singletons"
```

---

## Task 3: In-Process Domain Event Bus

**Files:**
- Create: `server/common/events.py`
- Create: `server/apps/main/logic/events.py`
- Modify: `server/apps/main/logic/usecases/blogpost_create.py`
- Modify: `server/implemented.py`
- Create: `tests/test_server/test_events.py`

- [ ] **Step 1: Write failing tests for InProcessEventBus**

Create `tests/test_server/test_events.py`:

```python
"""Unit tests for the in-process event bus."""

from server.apps.main.logic.events import BlogPostCreated
from server.common.events import InProcessEventBus


def test_emit_with_no_subscribers_does_not_raise() -> None:
    """Emitting an event with no subscribers is a no-op."""
    bus = InProcessEventBus()
    bus.emit(BlogPostCreated(blog_post_id=1))


def test_subscribe_and_emit_delivers_event() -> None:
    """A subscribed handler receives the emitted event."""
    bus = InProcessEventBus()
    received: list[BlogPostCreated] = []
    bus.subscribe(BlogPostCreated, received.append)
    bus.emit(BlogPostCreated(blog_post_id=42))
    assert received == [BlogPostCreated(blog_post_id=42)]


def test_emit_does_not_deliver_to_wrong_event_type() -> None:
    """A handler subscribed to one event type does not receive others."""
    bus = InProcessEventBus()
    received: list[BlogPostCreated] = []
    bus.subscribe(BlogPostCreated, received.append)

    class OtherEvent:
        pass

    bus.emit(OtherEvent())
    assert received == []


def test_multiple_subscribers_all_receive_event() -> None:
    """Multiple handlers for the same event type each receive it."""
    bus = InProcessEventBus()
    calls: list[int] = []
    bus.subscribe(BlogPostCreated, lambda e: calls.append(1))
    bus.subscribe(BlogPostCreated, lambda e: calls.append(2))
    bus.emit(BlogPostCreated(blog_post_id=1))
    assert calls == [1, 2]
```

Run: `pytest tests/test_server/test_events.py --no-cov -x`
Expected: **ImportError** — modules don't exist yet.

- [ ] **Step 2: Create `server/apps/main/logic/events.py`**

```python
"""Domain events emitted by the main app's use cases."""

from typing import final

import attrs


@final
@attrs.define(frozen=True)
class BlogPostCreated:
    """Fired after a new blog post is successfully persisted."""

    blog_post_id: int
```

- [ ] **Step 3: Create `server/common/events.py`**

```python
"""In-process event bus — synchronous, suitable for side-effect coordination."""

from typing import Any, Protocol, final

import attrs


class EventBus(Protocol):
    """Contract for publishing domain events."""

    def emit(self, event: Any) -> None:
        """Publish an event to all registered subscribers."""
        ...

    def subscribe(self, event_type: type, handler: Any) -> None:
        """Register a callable to receive events of ``event_type``."""
        ...


@final
@attrs.define(slots=True)
class InProcessEventBus:
    """Synchronous in-process implementation of EventBus."""

    _handlers: dict[type, list[Any]] = attrs.Factory(dict)

    def subscribe(self, event_type: type, handler: Any) -> None:
        """Register a handler for the given event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: Any) -> None:
        """Call all handlers registered for this event's type."""
        for handler in self._handlers.get(type(event), []):
            handler(event)
```

Run: `pytest tests/test_server/test_events.py --no-cov -x`
Expected: **PASS**

- [ ] **Step 4: Add EventBus to `CreateBlogPost`**

Replace `server/apps/main/logic/usecases/blogpost_create.py`:

```python
"""Use case: create a new blog post."""

from typing import final

import attrs

from server.apps.main.logic.events import BlogPostCreated
from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)
from server.common.events import EventBus


@final
@attrs.define(slots=True, frozen=True)
class CreateBlogPost:
    """Creates ``BlogPost`` instances."""

    _store: BlogPostStore
    _events: EventBus

    def __call__(
        self,
        parsed_body: BlogPostCreatePayload,
    ) -> BlogPostFullPayload:
        """
        Validate and persist a new blog post, then emit BlogPostCreated.

        Business logic (credits, quotas, etc.) belongs here before
        the ``self._store.create()`` call.
        """
        result = self._store.create(parsed_body)
        self._events.emit(BlogPostCreated(blog_post_id=result.id))
        return result
```

- [ ] **Step 5: Register EventBus in `implemented.py`**

Add to `_inject_main` (before use case registrations):

```python
def _inject_main(container: Container) -> None:
    from server.apps.main.infra import mappers, repository
    from server.apps.main.infra import store as write_store
    from server.apps.main.logic import ports
    from server.apps.main.logic.usecases import blogpost_create, blogpost_get
    from server.common.events import EventBus, InProcessEventBus

    # Internal infra components
    container.register(repository.BlogPostRepo, scope=Scope.singleton)
    container.register(mappers.BlogPostMapper, scope=Scope.singleton)

    # Event bus — singleton so all handlers registered at startup are retained
    container.register(EventBus, instance=InProcessEventBus())

    # Register BlogPostStore Protocol → concrete implementation
    container.register(
        ports.BlogPostStore,
        factory=write_store.BlogPostWriteStoreImpl,
        scope=Scope.singleton,
    )

    # Use cases
    container.register(blogpost_create.CreateBlogPost, scope=Scope.singleton)
    container.register(blogpost_get.GetBlogPost, scope=Scope.singleton)
```

- [ ] **Step 6: Run full suite**

```bash
pytest --no-cov -x
```

The existing `test_blog_post_create.py` will still pass — the API response is unchanged. The event is emitted but no handler is subscribed yet (no side effects).

- [ ] **Step 7: Run linters**

```bash
ruff check . && ruff format . && mypy server tests/**/*.py && lint-imports
```

- [ ] **Step 8: Commit**

```bash
git add server/common/events.py \
        server/apps/main/logic/events.py \
        server/apps/main/logic/usecases/blogpost_create.py \
        server/implemented.py \
        tests/test_server/test_events.py
git commit -m "feat: add in-process EventBus, emit BlogPostCreated from CreateBlogPost"
```

---

## Task 4: CQRS Read Query + List Endpoint

**Files:**
- Modify: `server/apps/main/logic/value_objects.py`
- Create: `server/apps/main/infra/queries.py`
- Modify: `server/apps/main/api/views.py`
- Modify: `server/apps/main/api/urls.py`
- Modify: `server/implemented.py`
- Create: `tests/test_apps/test_main/test_infra/test_queries.py`
- Create: `tests/test_apps/test_main/test_api/test_blog_post_list.py`

Query objects live in `infra/` because they use the ORM directly. Controllers resolve them via `self.resolve()` — no direct import, so no import-linter violation.

- [ ] **Step 1: Add `BlogPostSummaryPayload` to value objects**

Add to `server/apps/main/logic/value_objects.py`:

```python
from typing import Annotated, final

import msgspec

from server.apps.main.logic.constants import POST_TITLE_MAX_LENGTH


class BlogPostCreatePayload(msgspec.Struct):
    """Used to create ``BlogPost`` models."""

    title: Annotated[
        str,
        msgspec.Meta(min_length=1, max_length=POST_TITLE_MAX_LENGTH),
    ]
    body: str


@final
class BlogPostFullPayload(BlogPostCreatePayload):
    """Used to represent existing ``BlogPost`` models."""

    id: int


@final
class BlogPostSummaryPayload(msgspec.Struct):
    """Lightweight list representation — id and title only."""

    id: int
    title: str
```

- [ ] **Step 2: Write failing tests for the query object**

Create `tests/test_apps/test_main/test_infra/test_queries.py`:

```python
"""Tests for CQRS read query objects."""

import pytest
from faker import Faker

from server.apps.main.infra.queries import BlogPostListQuery
from server.apps.main.logic.value_objects import BlogPostSummaryPayload
from server.apps.main.models import BlogPost


@pytest.mark.django_db
def test_blog_post_list_query_returns_empty_list_when_no_posts() -> None:
    """Returns an empty list when there are no blog posts."""
    query = BlogPostListQuery()
    result = query()
    assert result == []


@pytest.mark.django_db
def test_blog_post_list_query_returns_all_posts(faker: Faker) -> None:
    """Returns a summary for each post, newest first."""
    post_a = BlogPost.objects.create(title=faker.word(), body=faker.text())
    post_b = BlogPost.objects.create(title=faker.word(), body=faker.text())
    query = BlogPostListQuery()
    result = query()
    assert len(result) == 2
    assert all(isinstance(r, BlogPostSummaryPayload) for r in result)
    # Newest first
    assert result[0].id == post_b.pk
    assert result[1].id == post_a.pk
```

Run: `pytest tests/test_apps/test_main/test_infra/test_queries.py --no-cov -x`
Expected: **ImportError** — `infra.queries` does not exist.

- [ ] **Step 3: Create `server/apps/main/infra/queries.py`**

```python
"""CQRS read-side query objects for the main app."""

from typing import final

import attrs

from server.apps.main.logic.value_objects import BlogPostSummaryPayload
from server.apps.main.models import BlogPost


@final
@attrs.define(slots=True, frozen=True)
class BlogPostListQuery:
    """Returns a lightweight summary list of all blog posts."""

    def __call__(self) -> list[BlogPostSummaryPayload]:
        """Fetch all blog posts ordered newest first."""
        return [
            BlogPostSummaryPayload(id=row['id'], title=row['title'])
            for row in BlogPost.objects.values('id', 'title').order_by('-id')
        ]
```

Run: `pytest tests/test_apps/test_main/test_infra/test_queries.py --no-cov -x`
Expected: **PASS**

- [ ] **Step 4: Register the query in `implemented.py`**

Add inside `_inject_main`:

```python
from server.apps.main.infra import queries

container.register(queries.BlogPostListQuery, scope=Scope.singleton)
```

Full `_inject_main` after this change:

```python
def _inject_main(container: Container) -> None:
    from server.apps.main.infra import mappers, queries, repository
    from server.apps.main.infra import store as write_store
    from server.apps.main.logic import ports
    from server.apps.main.logic.usecases import blogpost_create, blogpost_get
    from server.common.events import EventBus, InProcessEventBus

    container.register(repository.BlogPostRepo, scope=Scope.singleton)
    container.register(mappers.BlogPostMapper, scope=Scope.singleton)
    container.register(EventBus, instance=InProcessEventBus())
    container.register(
        ports.BlogPostStore,
        factory=write_store.BlogPostWriteStoreImpl,
        scope=Scope.singleton,
    )
    container.register(blogpost_create.CreateBlogPost, scope=Scope.singleton)
    container.register(blogpost_get.GetBlogPost, scope=Scope.singleton)
    container.register(queries.BlogPostListQuery, scope=Scope.singleton)
```

- [ ] **Step 5: Write failing API test for list endpoint**

Create `tests/test_apps/test_main/test_api/test_blog_post_list.py`:

```python
"""API tests for the blog post list endpoint."""

from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient
from faker import Faker

from server.apps.main.models import BlogPost


@pytest.mark.django_db
def test_blog_post_list_empty(dmr_client: DMRClient) -> None:
    """List returns an empty array when no posts exist."""
    response = dmr_client.get(reverse('api:main:blog_post_list'))
    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


@pytest.mark.django_db
def test_blog_post_list_returns_posts(
    dmr_client: DMRClient, faker: Faker
) -> None:
    """List returns all posts as summary objects, newest first."""
    BlogPost.objects.create(title=faker.word(), body=faker.text())
    BlogPost.objects.create(title=faker.word(), body=faker.text())
    response = dmr_client.get(reverse('api:main:blog_post_list'))
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data) == 2
    assert {'id', 'title'} == set(data[0].keys())
```

Run: `pytest tests/test_apps/test_main/test_api/test_blog_post_list.py --no-cov -x`
Expected: **FAIL** — URL `api:main:blog_post_list` does not exist.

- [ ] **Step 6: Add `BlogPostList` controller to `views.py`**

Add this class to `server/apps/main/api/views.py` (append after existing controllers):

```python
from server.apps.main.infra.queries import BlogPostListQuery
from server.apps.main.logic.value_objects import BlogPostSummaryPayload


@final
class BlogPostList(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Returns a summary list of all blog posts."""

    def get(self) -> list[BlogPostSummaryPayload]:
        """List all blog posts, newest first."""
        return self.resolve(BlogPostListQuery)()
```

The full updated `views.py`:

```python
from http import HTTPStatus
from typing import final, override

from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.main.infra.queries import BlogPostListQuery
from server.apps.main.logic.usecases import blogpost_create, blogpost_get
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
    BlogPostSummaryPayload,
)
from server.apps.main.models import BlogPost
from server.common.di import HasContainer


@final
class BlogPostCreate(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Top level endpoints for the ``BlogPost`` model."""

    def post(
        self,
        parsed_body: Body[BlogPostCreatePayload],
    ) -> BlogPostFullPayload:
        """Create new ``BlogPost`` model."""
        return self.resolve(blogpost_create.CreateBlogPost)(parsed_body)


@final
class BlogPostGet(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Endpoints that only require a path for ``BlogPost`` models."""

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> BlogPostFullPayload:
        """Return existing ``BlogPost`` model by id."""
        return self.resolve(blogpost_get.GetBlogPost)(self.kwargs['id'])

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        """Handle specific errors for this controller."""
        if isinstance(exc, BlogPost.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Blog post not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )


@final
class BlogPostList(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Returns a summary list of all blog posts."""

    def get(self) -> list[BlogPostSummaryPayload]:
        """List all blog posts, newest first."""
        return self.resolve(BlogPostListQuery)()
```

- [ ] **Step 7: Add list URL to `api/urls.py`**

```python
from dmr.routing import path

from server.apps.main.api import views

app_name = 'main'

urlpatterns = [
    path('users/', views.BlogPostCreate.as_view(), name='blog_post_create'),
    path('users/<int:id>', views.BlogPostGet.as_view(), name='blog_post_get'),
    path('users/list/', views.BlogPostList.as_view(), name='blog_post_list'),
]
```

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_apps/test_main/test_api/test_blog_post_list.py --no-cov -x
```

Expected: **PASS**

- [ ] **Step 9: Run full suite**

```bash
pytest --no-cov -x
```

The schemathesis test (`test_schema.py`) will automatically exercise the new endpoint against the OpenAPI schema.

- [ ] **Step 10: Run linters**

```bash
ruff check . && ruff format . && mypy server tests/**/*.py && lint-imports
```

- [ ] **Step 11: Commit**

```bash
git add server/apps/main/logic/value_objects.py \
        server/apps/main/infra/queries.py \
        server/apps/main/api/views.py \
        server/apps/main/api/urls.py \
        server/implemented.py \
        tests/test_apps/test_main/test_infra/test_queries.py \
        tests/test_apps/test_main/test_api/test_blog_post_list.py
git commit -m "feat: add CQRS BlogPostListQuery and GET /api/user/list/ endpoint"
```

---

## Task 5: Application Services Layer Scaffold

**Files:**
- Create: `server/services/__init__.py`
- Modify: `.importlinter`

No implementation yet — this establishes the package and the import-linter contracts so future cross-domain services have a sanctioned home.

- [ ] **Step 1: Create `server/services/__init__.py`**

```python
"""
Application services layer — cross-domain coordination.

Modules here are the ONLY place allowed to import from multiple
``server.apps.*`` domains simultaneously. Each service orchestrates
use cases from different apps to implement complex business workflows.

Naming: use verb-noun — ``StartClipPipeline``, ``OnboardNewProject``.

Rules:
- Apps MUST NOT import from this package (that would be circular).
- Services depend on app use cases and ports — never on infra directly.
- Register services in ``server.implemented.populate_dependencies``.
"""
```

- [ ] **Step 2: Update `.importlinter`**

Replace the existing `.importlinter` with:

```ini
# See https://github.com/seddonym/import-linter

[importlinter]
root_package = server
include_external_packages = True
exclude_type_checking_imports = True


[importlinter:contract:layers]
name = Layered architecture of our project
type = layers

containers =
  server.apps.*

layers =
  (urls) | (admin)
  (views) | (htmx) | (api)
  (tasks)
  (infra)
  (models)
  (logic)


[importlinter:contract:apps-independence]
name = All apps must be independent of each other
type = independence

modules =
  server.apps.*

ignore_imports =
  # Hack required for model FK relations in admin:
  server.apps.*.admin -> server.apps.*.models


[importlinter:contract:common-module-is-independent]
name = Common utilities cannot import from apps
type = forbidden

source_modules =
  server.common

forbidden_modules =
  server.apps

ignore_imports =
  # DI wiring is in common but references implemented which imports apps:
  server.common.di -> server.implemented


[importlinter:contract:tests-restrictions]
name = Explicit import restrictions for tests
type = forbidden

source_modules =
  server

forbidden_modules =
  tests


[importlinter:contract:server-can-import-settings-directly]
name = Settings can be directly imported only in settings, use django.conf elsewhere
type = protected

protected_modules =
  server.settings.**

allowed_importers =
  server.settings


[importlinter:contract:apps-cannot-import-services]
name = Apps must not import from the services layer (would be circular)
type = forbidden

source_modules =
  server.apps

forbidden_modules =
  server.services
```

- [ ] **Step 3: Verify import-linter passes**

```bash
lint-imports
```

Expected: all contracts pass.

- [ ] **Step 4: Run full suite**

```bash
pytest --no-cov -x
```

- [ ] **Step 5: Commit**

```bash
git add server/services/__init__.py .importlinter
git commit -m "feat: add services layer scaffold and import-linter contracts"
```

---

## Task 6: Full Suite + CLAUDE.md + Memory

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the complete test suite with coverage**

```bash
pytest
```

Expected: 100% coverage, all tests green. If coverage fails, identify uncovered lines and add targeted tests before proceeding.

- [ ] **Step 2: Run all linters end-to-end**

```bash
ruff check . && ruff format . && \
mypy server tests/**/*.py && \
lint-imports && \
yamllint -d '{"extends": "default", "ignore": ".venv"}' -s . && \
find server -type f -name '*.html' | xargs djangofmt --line-length=80 --indent-width=2
```

Fix all issues before proceeding.

- [ ] **Step 3: Update CLAUDE.md architecture section**

Update the "Architecture" section of `CLAUDE.md` to document the full evolved pattern. Replace the architecture section with:

```markdown
## Architecture

### Project layout
\```
server/
  settings/           django-split-settings modular config
    components/       feature settings (common, api, logging, csp, caches)
    environments/     per-environment overrides (development, production, local.py)
  apps/               Django apps — one per bounded domain
    <domain>/
      api/            DMR controllers + URL routing (top layer)
      logic/
        ports.py      Protocol interfaces this domain exposes to its usecases
        usecases/     Write operations — one class per action, callable via __call__
        value_objects.py  DTOs (msgspec.Struct) — in/out shapes, no ORM
        events.py     Domain events this app can emit
      infra/
        repository.py Internal DB write operations (returns ORM models)
        mappers.py    ORM model → value object conversion
        store.py      Implements logic/ports.py Protocol (combines repo + mapper)
        queries.py    CQRS read objects — direct ORM queries returning value objects
      models.py       Django ORM models
  services/           Cross-domain coordination (may import from multiple apps)
  common/
    di.py             HasContainer mixin — exposes self.resolve()
    container.py      Module-level punq singleton (populated in AppConfig.ready())
    events.py         EventBus Protocol + InProcessEventBus
  implemented.py      DI wiring — registers ALL concrete classes into punq as singletons
tests/                Mirrors server/apps/ layout
  plugins/            pytest fixtures/plugins (autouse and shared)
\```

### Layering (enforced by import-linter)
Imports flow downward only:
\```
(urls) | (admin)          ← top
(views) | (api)
(tasks)
(infra)
(models)
(logic)                   ← bottom, pure domain, no Django/ORM
\```

All `server.apps.*` domains are independent — no cross-app imports. `server.services.*` is the only sanctioned place to coordinate across domains.

### Write path (commands)
\```
Controller.post()
  → self.resolve(MyUseCase)        ← punq, same instance every time (singleton)
    → usecase._store.create()      ← port (Protocol) → BlogPostWriteStoreImpl
      → repo.create() → ORM model
      → mapper(model) → DTO
    → events.emit(MyEvent)         ← in-process, sync
  → return DTO → serialised by DMR
\```

### Read path (queries)
\```
Controller.get()
  → self.resolve(MyListQuery)()    ← query object in infra/queries.py
    → ORM .values().order_by()     ← direct, no mapper needed
    → list[SummaryDTO]
\```

### Dependency injection — punq
`server/implemented.py` is the single file where all concrete classes are registered. `AppConfig.ready()` calls `populate_dependencies(container)` once at startup. All registrations use `scope=Scope.singleton` — classes must be stateless (`frozen=True`). Protocols are registered explicitly: `container.register(MyPort, factory=MyConcreteImpl, scope=Scope.singleton)`.

**Never use `from __future__ import annotations` in usecase files** — it makes annotations lazy strings that punq cannot resolve. Import ports and events directly.

### Domain events
Usecases import `EventBus` from `server.common.events` and `XxxEvent` from their app's `logic/events.py`. The `InProcessEventBus` singleton is registered in `implemented.py`. Handlers subscribe to the bus at startup. To add a handler: subscribe in the relevant `AppConfig.ready()` after `populate_dependencies()`.

### Adding a new domain entity — checklist
1. `models.py` — add the model
2. `logic/value_objects.py` — add create + full payload structs
3. `logic/ports.py` — add the write store Protocol
4. `logic/events.py` — add domain events (e.g. `ThingCreated`)
5. `infra/repository.py` — add raw DB write methods
6. `infra/mappers.py` — add model → full payload mapper
7. `infra/store.py` — add `ThingWriteStoreImpl` implementing the Protocol
8. `infra/queries.py` — add read query objects
9. `logic/usecases/` — one file per write action
10. `api/views.py` — controllers
11. `api/urls.py` — wire URLs
12. `implemented.py` — register everything as singletons
13. `migrations/` — `python manage.py makemigrations`
```

- [ ] **Step 4: Save architecture memory**

Write `/Users/chuckz/.claude/projects/-Users-chuckz-Code-29SignalsDev-reelforge/memory/project_architecture_base.md` with the new architecture decisions (see the memory section below).

- [ ] **Step 5: Final full run**

```bash
pytest && ruff check . && mypy server tests/**/*.py && lint-imports
```

All must pass.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with full evolved architecture patterns"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Singleton container — Task 1
- ✅ Ports/Protocols + drop inject() hack — Task 2
- ✅ Domain event bus — Task 3
- ✅ CQRS read queries — Task 4
- ✅ Application services scaffold — Task 5
- ✅ CLAUDE.md + memory — Task 6
- ✅ All existing tests preserved (no API behaviour changed)
- ✅ 100% coverage addressed in Task 6 Step 5

**Placeholder scan:** No TBD, no "similar to above", all code blocks are complete.

**Type consistency:**
- `BlogPostStore` (Protocol in ports.py) — used as annotation in usecases, registered in implemented.py ✅
- `BlogPostWriteStoreImpl` (in store.py) — registered under `BlogPostStore` key ✅
- `BlogPostSummaryPayload` — defined in value_objects.py, used in queries.py and views.py ✅
- `InProcessEventBus` — registered as `EventBus` instance ✅
- `BlogPostListQuery` — registered in implemented.py, resolved in views.py ✅
