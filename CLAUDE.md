# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup
```bash
poetry install                    # install all dependencies
poetry install --only=main        # production deps only
poetry install --with=docs        # include docs dependencies
```

### Run (local, without Docker app container)
```bash
# Bring up only the database in Docker:
docker compose up -d db

# Run the dev server locally:
python manage.py runserver

# Or run fully containerized:
docker compose up
```

Config is loaded from `config/.env` by python-decouple. Copy `config/.env.template` to `config/.env` and fill in values. The `DJANGO_ENV` env var controls which settings environment is active (`development` by default, `production` for prod).

### Manage Django
```bash
python manage.py migrate
python manage.py makemigrations
python manage.py createsuperuser
python manage.py shell
```

### Tests
```bash
pytest                                        # all tests (requires 100% coverage)
pytest tests/test_apps/test_main/             # single app
pytest tests/test_apps/test_main/test_api/test_blog_post_create.py  # single file
pytest --no-cov                               # skip coverage (faster in TDD)
```

### Linting & type checking
```bash
ruff check && ruff format          # lint + format (configured in pyproject.toml)
flake8 .                           # wemake-python-styleguide (WPS + E99 only)
mypy server tests/**/*.py          # type checking
lint-imports                       # enforce layered architecture contracts
yamllint -d '{"extends": "default", "ignore": ".venv"}' -s .
find server -type f -name '*.html' | xargs djangofmt --line-length=80 --indent-width=2
dotenv-linter config/.env config/.env.template
polint -i location,unsorted locale
```

### Migration checks
```bash
python manage.py lintmigrations                        # backward-compatible migrations
python manage.py check_migrations --exclude-apps=axes  # safe for zero-downtime
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
      infra/          repository + mapper classes (DB access layer)
      logic/          pure domain: usecases/, value_objects.py, constants.py
      models.py       Django ORM models
  common/             shared utilities (no imports from server.apps.*)
    di.py             HasContainer mixin + punq container resolution
  implemented.py      DI wiring — registers all concrete classes into punq
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

All apps in `server.apps.*` are independent — no cross-app imports (enforced). `server.common` cannot import from `server.apps.*`.

### API layer — django-modern-rest (DMR)
Controllers inherit from `dmr.Controller` and optionally `HasContainer` for DI. Request parsing uses `Body[PayloadType]`. Payloads are `msgspec.Struct` subclasses defined in `logic/value_objects.py`.

```python
class MyController(HasContainer, Controller[MsgspecSerializer]):
    def post(self, parsed_body: Body[MyPayload]) -> MyResponsePayload:
        return self.resolve(my_usecase.MyUseCase)(parsed_body)
```

### Dependency injection — punq
`server/implemented.py` is the single place where all concrete implementations are registered. `HasContainer.resolve(SomeUseCase)` retrieves a fully-wired instance per request.

### Settings
`DJANGO_SETTINGS_MODULE = "server.settings"` — the `__init__.py` uses django-split-settings to compose components and then overlay the active environment file. A `server/settings/environments/local.py` (gitignored) can override anything locally without touching tracked files.

### Testing patterns
- Test files use `@pytest.mark.django_db` for DB access.
- Factories use `polyfactory` with `MsgspecFactory` for value objects.
- `dmr.test.DMRClient` (not Django's `Client`) for API endpoint tests.
- Pytest plugins in `tests/plugins/` (registered in `conftest.py`) provide autouse fixtures for media root, password hashers, and Axes backend.
- 100% coverage is required — `--cov-fail-under=100` is hardcoded in `pyproject.toml`.

## Key constraints
- Python 3.13.13 (pinned in `.python-version`).
- Django 6.0.x (pinned in `pyproject.toml`).
- `ruff` uses single quotes and 80-char line length.
- `mypy` runs in strict mode — all public functions need type annotations.
- Migrations must be backward-compatible (zero-downtime) — migration linter will fail otherwise.
- `ZEAL_RAISE = True` in development: N+1 queries raise exceptions, not just warnings.
