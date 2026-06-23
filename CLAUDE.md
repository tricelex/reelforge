# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup
```bash
# All development happens inside the running Docker web container.
# Start it once and exec into it for all commands:
docker compose up -d
docker compose exec web bash
```

### Run manage.py commands
```bash
just run migrate
just run makemigrations
just run createsuperuser
just run shell
```
`just run <cmd>` sources `.env.local` and calls `python manage.py <cmd>` without needing the app container.

### Tests
```bash
docker compose exec web pytest                          # all tests (requires 100% coverage)
docker compose exec web pytest tests/test_apps/test_main/          # single app
docker compose exec web pytest tests/test_apps/test_main/test_api/test_blog_post_create.py  # single file
docker compose exec web pytest --no-cov                # skip coverage (faster in TDD)
```

### Linting & type checking
```bash
docker compose exec web ruff check .                   # lint
docker compose exec web ruff format --check .          # format check
docker compose exec web mypy server                    # strict type checking
docker compose exec web lint-imports                   # enforce layered architecture contracts
```

### Migration checks
```bash
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```

## Architecture

### Project layout
```
server/               Django project root (Python package)
  settings/           django-split-settings modular config
    components/       feature-specific settings (common, api, logging, csp, caches)
    environments/     per-environment overrides (development, production, local.py)
  apps/               Django apps (one dir per bounded context)
    main/             example/template app
      services.py     ALL business logic + DB ops for this app (one class per domain)
      models.py       Django ORM models
      logic/          pure domain types — value_objects.py, events.py, constants.py
      api/            DMR controllers + URL routing
  common/             shared utilities (no imports from server.apps.*)
    container.py      module-level punq singleton, populated once at startup
    di.py             HasContainer mixin — resolve() delegates to container singleton
    events.py         EventBus Protocol + InProcessEventBus implementation
  services/           cross-app orchestration (may import from multiple apps)
  implemented.py      DI wiring — all Scope.singleton registrations go here
  urls.py             root URL conf with OpenAPI docs + health check
tests/                mirrors server/apps/ layout; not a Python package
  plugins/            pytest fixtures/plugins
```

### Per-app structure (new entity checklist)
Every domain entity in an app follows this minimal structure:

1. `models.py` — Django ORM model
2. `logic/value_objects.py` — msgspec.Struct input/output DTOs
3. `logic/events.py` — domain events (attrs frozen dataclass, e.g. `ThingCreated`)
4. `services.py` — one `@final @attrs.define` class with all read + write methods
5. `api/views.py` — thin controllers that delegate to the service
6. `api/urls.py` — URL routing
7. `implemented.py` — register the service as a singleton
8. `just run makemigrations` — generate migration

### Layered architecture (enforced by import-linter)
Imports flow strictly downward — upper layers may import from lower, never the reverse:

```
(urls) | (admin)
(views) | (api)
(tasks)
(models)
(logic)
```

All apps in `server.apps.*` are independent — no cross-app imports.
`server.common` cannot import from `server.apps.*`.
`server.apps.*` cannot import from `server.services` (services may import from apps, never the reverse).

### Dependency injection — punq singleton container

The global container lives in `server/common/container.py`. It is populated **once** in
`MainConfig.ready()` by calling `implemented.populate_dependencies(container)`.

All registrations use `Scope.singleton`. Every class stored in the container must be
`frozen=True` (stateless — no mutable fields).

Adding a new service in `implemented.py`:
```python
def _inject_myapp(container: Container) -> None:
    from server.apps.myapp.services import MyService
    from server.common.events import EventBus

    # EventBus already registered — punq injects it automatically
    container.register(MyService, scope=Scope.singleton)
```

Controllers retrieve instances via `self.resolve(MyService)` — never construct manually.

**CRITICAL:** Never add `from __future__ import annotations` to files registered with punq.
It makes annotations lazy strings punq cannot resolve at registration time.

### Service pattern
Each app has a single service class that owns all DB operations and business logic:

```python
@final
@attrs.define(slots=True, frozen=True)
class BlogPostService:
    _events: EventBus  # injected by punq

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        post = BlogPost.objects.create(title=payload.title, body=payload.body)
        result = BlogPostFullPayload(
            id=post.pk, title=post.title, body=post.body
        )
        self._events.emit(BlogPostCreated(blog_post_id=result.id))
        return result

    def get_by_id(self, post_id: int) -> BlogPostFullPayload:
        post = BlogPost.objects.get(pk=post_id)
        return BlogPostFullPayload(id=post.pk, title=post.title, body=post.body)

    def list_all(self) -> list[BlogPostSummaryPayload]:
        return [
            BlogPostSummaryPayload(id=r['id'], title=r['title'])
            for r in BlogPost.objects.values('id', 'title').order_by('-id')
        ]
```

Write methods emit domain events. Read methods (list/get) return lightweight value objects
directly from ORM `.values()` calls — no separate mapper needed.

### Domain events — EventBus
`server/common/events.py` has `EventBus` Protocol + `InProcessEventBus` (registered as
singleton in `implemented.py`). App events live in `logic/events.py`.

Emit in a service method:
```python
self._events.emit(BlogPostCreated(blog_post_id=result.id))
```

Subscribe a handler (e.g. in `AppConfig.ready()` after `populate_dependencies()`):
```python
bus = container.resolve(EventBus)
bus.subscribe(BlogPostCreated, some_handler_function)
```

### API layer — django-modern-rest (DMR)
Controllers inherit from `Controller[MsgspecSerializer]` and `HasContainer`. Payloads are
`msgspec.Struct` subclasses defined in `logic/value_objects.py`. Controllers are thin —
they only parse input, call `self.resolve(MyService).method()`, and return the result.

### Application Services layer
`server/services/` is for orchestrators that coordinate multiple apps. Import freely from
any `server.apps.*` package here, but apps must never import back into services. Enforced
by import-linter contract `apps-cannot-import-services`.

### Class conventions
- `@final` on every concrete class (mypy-enforced, prevents subclassing).
- `@attrs.define(slots=True, frozen=True)` for all service objects (stateless, thread-safe).
- Value objects use `msgspec.Struct` (fast serialisation, strict typing).
- Domain events use `@attrs.define(frozen=True)` (immutable, no slots needed).

### Settings
`DJANGO_SETTINGS_MODULE = "server.settings"` — composes components then overlays the
active environment. `server/settings/environments/local.py` (gitignored) for local overrides.

### Testing patterns
- `@pytest.mark.django_db` for any test that touches the ORM.
- `dmr.test.DMRClient` for API endpoint tests (not Django's `Client`).
- Factories use `polyfactory` with `MsgspecFactory` for value objects.
- 100% coverage required — `--cov-fail-under=100` in `pyproject.toml`.
- `--doctest-modules` is active — docstring code examples must be valid.
- No `from __future__ import annotations` in files used by punq.

## Key constraints
- Python 3.13.x.
- Django 6.0.x.
- `ruff` uses single quotes, 80-char line length.
- `mypy` runs in strict mode — all public functions need type annotations.
- Migrations must be backward-compatible (zero-downtime) — migration linter enforces this.
- `ZEAL_RAISE = True` in development: N+1 queries raise exceptions.
- `server/apps/*/apps.py` is exempt from `PLC0415` (inline imports in `ready()` required by Django).
