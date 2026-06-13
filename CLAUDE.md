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
      api/            DMR controllers + URL routing
      infra/          repository, mapper, store, queries (DB access layer)
      logic/          pure domain: usecases/, ports.py, value_objects.py, events.py
      models.py       Django ORM models
  common/             shared utilities (no imports from server.apps.*)
    container.py      module-level punq singleton, populated once at startup
    di.py             HasContainer mixin — resolve() delegates to container singleton
    events.py         EventBus Protocol + InProcessEventBus implementation
  services/           cross-app application services (may import from multiple apps)
  implemented.py      DI wiring — all Scope.singleton registrations go here
  urls.py             root URL conf with OpenAPI docs + health check
tests/                mirrors server/apps/ layout; not a Python package
  plugins/            pytest fixtures/plugins
```

### Layered architecture (enforced by import-linter)
Imports flow strictly downward — upper layers may import from lower, never the reverse:

```
(urls) | (admin)
(views) | (api)
(tasks)
(infra)
(models)
(logic)
```

All apps in `server.apps.*` are independent — no cross-app imports.
`server.common` cannot import from `server.apps.*`.
`server.apps.*` cannot import from `server.services` (services may import from apps, never the reverse).

### Dependency injection — punq singleton container

The global container lives in `server/common/container.py`:
```python
container: punq.Container = punq.Container()
```

It is populated **once** in `MainConfig.ready()` by calling `implemented.populate_dependencies(container)`. All registrations use `Scope.singleton`.

**Never** build a new container per-request. **Never** use the old `inject()` / `_create_injector` pattern.

Registering a new dependency in `implemented.py`:
```python
def _inject_main(container: Container) -> None:
    from server.apps.main.infra import repository
    from server.apps.main.logic import ports
    from server.apps.main.infra import store

    container.register(repository.MyRepo, scope=Scope.singleton)
    container.register(
        ports.MyPort, factory=store.MyStoreImpl, scope=Scope.singleton
    )
```

### Ports / Protocols pattern
Usecases depend on **Protocols** (in `logic/ports.py`), not on concrete infra classes. This keeps logic and infra strictly decoupled:

```python
# logic/ports.py
class BlogPostStore(Protocol):
    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload: ...


# infra/store.py  — satisfies the Protocol structurally
@final
@attrs.define(slots=True, frozen=True)
class BlogPostWriteStoreImpl:
    _repository: BlogPostRepo
    _mapper: BlogPostMapper

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        return self._mapper(self._repository.create(payload))
```

Register the Protocol → concrete mapping in `implemented.py`:
```python
container.register(
    ports.BlogPostStore,
    factory=store.BlogPostWriteStoreImpl,
    scope=Scope.singleton,
)
```

### CQRS — separate write usecases from read queries
- **Write side**: `logic/usecases/` — callable `@attrs.define` classes that take a Port and an EventBus.
- **Read side**: `infra/queries.py` — callable `@attrs.define` classes that hit the DB directly (via ORM `.values()` calls) and return lightweight value objects.

Read query example:
```python
@final
@attrs.define(slots=True, frozen=True)
class BlogPostListQuery:
    def __call__(self) -> list[BlogPostSummaryPayload]:
        return [
            BlogPostSummaryPayload(id=row['id'], title=row['title'])
            for row in BlogPost.objects.values('id', 'title').order_by('-id')
        ]
```

### Domain events — EventBus
`server/common/events.py` defines the `EventBus` Protocol and an `InProcessEventBus` implementation. Domain event dataclasses live in `apps/<app>/logic/events.py`.

Emit in a usecase:
```python
self._events.emit(BlogPostCreated(blog_post_id=result.id))
```

Subscribe a handler (e.g., in `implemented.py` or `apps.py`):
```python
bus = container.resolve(EventBus)
bus.subscribe(BlogPostCreated, send_welcome_email)
```

### API layer — django-modern-rest (DMR)
Controllers inherit from `Controller[MsgspecSerializer]` and `HasContainer`. Payloads are `msgspec.Struct` subclasses defined in `logic/value_objects.py`.

```python
@final
class BlogPostCreate(HasContainer, Controller[MsgspecSerializer]):
    def post(
        self, parsed_body: Body[BlogPostCreatePayload]
    ) -> BlogPostFullPayload:
        return self.resolve(blogpost_create.CreateBlogPost)(parsed_body)
```

### Application Services layer
`server/services/` holds orchestrators that coordinate multiple apps. Import freely from any `server.apps.*` package here, but apps must never import back into services. Enforced by import-linter contract `apps-cannot-import-services`.

### Class conventions
- `@final` on every concrete class (mypy-enforced, prevents subclassing).
- `@attrs.define(slots=True, frozen=True)` for all immutable service objects.
- `__call__` makes usecases and queries callable objects (no extra method naming).
- No `from __future__ import annotations` in files resolved by punq — punq needs live type objects at registration time.

### Settings
`DJANGO_SETTINGS_MODULE = "server.settings"` — composes components then overlays the active environment. `server/settings/environments/local.py` (gitignored) for local overrides.

### Testing patterns
- `@pytest.mark.django_db` for any test that touches the ORM.
- `dmr.test.DMRClient` for API endpoint tests (not Django's `Client`).
- Factories use `polyfactory` with `MsgspecFactory` for value objects.
- 100% coverage required — `--cov-fail-under=100` in `pyproject.toml`.
- `--doctest-modules` is active — docstring code examples must be valid.
- No invalid `from __future__ import annotations` in files used by punq.

## Key constraints
- Python 3.13.x.
- Django 6.0.x.
- `ruff` uses single quotes, 80-char line length.
- `mypy` runs in strict mode — all public functions need type annotations.
- Migrations must be backward-compatible (zero-downtime) — migration linter enforces this.
- `ZEAL_RAISE = True` in development: N+1 queries raise exceptions.
- `server/apps/*/apps.py` is exempt from `PLC0415` (inline imports in `ready()` required by Django).
