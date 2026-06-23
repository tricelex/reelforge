# Sentry + Logfire Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-grade error tracking (Sentry) and distributed tracing (Logfire) to all three ReelForge processes — Django web server, Taskiq background worker, and scheduler.

**Architecture:** Sentry and Logfire run independently as complementary tools. A permanent `server/apps/core/` infrastructure app initialises both at Django startup via `AppConfig.ready()`, covering all three processes because each calls `django.setup()`. A custom `ObservabilityMiddleware` wraps every Taskiq task execution with Logfire spans and Sentry error capture. Structlog's existing stdlib bridge feeds both tools automatically with no changes to the logging config.

**Tech Stack:** `sentry-sdk[django]`, `logfire[django,httpx,redis,psycopg2,system-metrics]`, `taskiq.TaskiqMiddleware`, `contextvars.ContextVar` (async-safe span lifecycle), `unittest.mock.patch` (tests avoid hitting real backends)

---

## File Map

| File | Change | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add 2 runtime deps |
| `server/settings/__init__.py` | Modify | Include observability component |
| `server/settings/components/observability.py` | **Create** | 6 env-var-backed config values |
| `server/settings/components/common.py` | Modify | Add `server.apps.core` to INSTALLED_APPS |
| `server/common/observability.py` | **Create** | `init_sentry()`, `init_logfire()` |
| `server/common/taskiq_middleware.py` | **Create** | `ObservabilityMiddleware` |
| `server/common/broker.py` | Modify | Wire middleware onto broker |
| `server/apps/core/__init__.py` | **Create** | Empty package marker |
| `server/apps/core/apps.py` | **Create** | `CoreConfig.ready()` calls both inits |
| `.env.example` | Modify | Document new env vars |
| `tests/test_server/test_observability.py` | **Create** | 4 tests for init functions |
| `tests/test_server/test_taskiq_middleware.py` | **Create** | 5 tests for middleware |
| `tests/test_apps/test_core/test_apps.py` | **Create** | 1 test for CoreConfig.ready() |

---

## Task 1: Install Runtime Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies via poetry inside the Docker container**

```bash
docker compose exec web poetry add "sentry-sdk[django]" "logfire[django,httpx,redis,psycopg2,system-metrics]"
```

Expected: both packages and their transitive deps are resolved and written to `pyproject.toml` and `poetry.lock`.

- [ ] **Step 2: Verify packages imported cleanly**

```bash
docker compose exec web python -c "import sentry_sdk; import logfire; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore(deps): add sentry-sdk and logfire for observability"
```

---

## Task 2: Observability Settings Component

**Files:**
- Create: `server/settings/components/observability.py`
- Modify: `server/settings/__init__.py`

- [ ] **Step 1: Create the settings component**

Create `server/settings/components/observability.py`:

```python
from server.settings.components import config

DJANGO_ENV: str = config('DJANGO_ENV', default='development')

SENTRY_DSN: str = config('SENTRY_DSN', default='')
SENTRY_TRACES_SAMPLE_RATE: float = config(
    'SENTRY_TRACES_SAMPLE_RATE',
    cast=float,
    default=1.0,
)
SENTRY_PROFILES_SAMPLE_RATE: float = config(
    'SENTRY_PROFILES_SAMPLE_RATE',
    cast=float,
    default=0.1,
)

LOGFIRE_TOKEN: str = config('LOGFIRE_TOKEN', default='')
LOGFIRE_SERVICE_NAME: str = config('LOGFIRE_SERVICE_NAME', default='***REMOVED***')
```

- [ ] **Step 2: Add to the split-settings include list**

In `server/settings/__init__.py`, add `'components/observability.py'` to `_base_settings` after `'components/api.py'`:

```python
_base_settings = (
    'components/common.py',
    'components/logging.py',
    'components/csp.py',
    'components/caches.py',
    'components/api.py',
    'components/observability.py',  # ← add this line
    # Select the right env:
    f'environments/{_ENV}.py',
    # Optionally override some settings:
    optional('environments/local.py'),
)
```

- [ ] **Step 3: Verify Django loads cleanly**

```bash
docker compose exec web python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit**

```bash
git add server/settings/components/observability.py server/settings/__init__.py
git commit -m "feat(settings): add observability settings component"
```

---

## Task 3: Core Init Functions (TDD)

**Files:**
- Create: `server/common/observability.py`
- Create: `tests/test_server/test_observability.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server/test_observability.py`:

```python
"""Tests for server/common/observability.py."""

from unittest.mock import call, patch

from server.common.observability import init_logfire, init_sentry


def test_init_sentry_is_noop_without_dsn(settings) -> None:
    """init_sentry does nothing when SENTRY_DSN is empty."""
    settings.SENTRY_DSN = ''
    with patch('sentry_sdk.init') as mock_init:
        init_sentry()
    mock_init.assert_not_called()


def test_init_sentry_calls_sdk_init_with_correct_config(settings) -> None:
    """init_sentry passes DSN, env, sample rates, and correct integrations."""
    settings.SENTRY_DSN = 'https://key@o123.ingest.sentry.io/456'
    settings.DJANGO_ENV = 'test'
    settings.SENTRY_TRACES_SAMPLE_RATE = 0.5
    settings.SENTRY_PROFILES_SAMPLE_RATE = 0.05
    with patch('sentry_sdk.init') as mock_init:
        init_sentry()
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs['dsn'] == 'https://key@o123.ingest.sentry.io/456'
    assert kwargs['environment'] == 'test'
    assert kwargs['traces_sample_rate'] == 0.5
    assert kwargs['profiles_sample_rate'] == 0.05
    assert kwargs['send_default_pii'] is False


def test_init_logfire_is_noop_without_token(settings) -> None:
    """init_logfire does nothing when LOGFIRE_TOKEN is empty."""
    settings.LOGFIRE_TOKEN = ''
    with patch('logfire.configure') as mock_configure:
        init_logfire()
    mock_configure.assert_not_called()


def test_init_logfire_configures_and_instruments_all_integrations(
    settings,
) -> None:
    """init_logfire calls configure then all five instrument_* functions."""
    settings.LOGFIRE_TOKEN = 'pylf_v1_test_abc123'
    settings.LOGFIRE_SERVICE_NAME = '***REMOVED***-test'
    with (
        patch('logfire.configure') as mock_configure,
        patch('logfire.instrument_django') as mock_django,
        patch('logfire.instrument_psycopg2') as mock_psycopg2,
        patch('logfire.instrument_redis') as mock_redis,
        patch('logfire.instrument_httpx') as mock_httpx,
        patch('logfire.instrument_logging') as mock_logging,
    ):
        init_logfire()
    mock_configure.assert_called_once_with(
        token='pylf_v1_test_abc123',
        service_name='***REMOVED***-test',
    )
    mock_django.assert_called_once_with(capture_headers=True)
    mock_psycopg2.assert_called_once_with()
    mock_redis.assert_called_once_with()
    mock_httpx.assert_called_once_with()
    mock_logging.assert_called_once_with()
```

- [ ] **Step 2: Run tests — confirm they fail with ImportError**

```bash
docker compose exec web pytest tests/test_server/test_observability.py --no-cov -v
```

Expected: `ImportError: cannot import name 'init_logfire' from 'server.common.observability'` (module doesn't exist yet).

- [ ] **Step 3: Implement `server/common/observability.py`**

```python
"""Sentry and Logfire initialisation helpers."""

import logging

import logfire
import sentry_sdk
from django.conf import settings
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration


def init_sentry() -> None:
    """Initialise Sentry SDK. No-op when SENTRY_DSN is not configured."""
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.DJANGO_ENV,
        integrations=[
            DjangoIntegration(transaction_style='url'),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
            RedisIntegration(),
        ],
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        send_default_pii=False,
    )


def init_logfire() -> None:
    """Initialise Logfire. No-op when LOGFIRE_TOKEN is not configured."""
    if not settings.LOGFIRE_TOKEN:
        return
    logfire.configure(
        token=settings.LOGFIRE_TOKEN,
        service_name=settings.LOGFIRE_SERVICE_NAME,
    )
    logfire.instrument_django(capture_headers=True)
    logfire.instrument_psycopg2()
    logfire.instrument_redis()
    logfire.instrument_httpx()
    logfire.instrument_logging()
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
docker compose exec web pytest tests/test_server/test_observability.py --no-cov -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Check for deprecation warnings from the new SDKs**

```bash
docker compose exec web pytest tests/test_server/test_observability.py --no-cov -W error -v 2>&1 | grep -i "warning\|deprecated" || echo "no warnings"
```

If sentry-sdk or logfire emit DeprecationWarnings, add suppressors to `pyproject.toml` under `filterwarnings`:

```toml
filterwarnings = [
  "error",
  "ignore::DeprecationWarning:sentry_sdk",
  "ignore::DeprecationWarning:logfire",
]
```

- [ ] **Step 6: Run lint and type check**

```bash
docker compose exec web ruff check server/common/observability.py
docker compose exec web mypy server/common/observability.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add server/common/observability.py tests/test_server/test_observability.py
git commit -m "feat(observability): add init_sentry and init_logfire core functions"
```

---

## Task 4: Core Infrastructure App (TDD)

**Files:**
- Create: `server/apps/core/__init__.py`
- Create: `server/apps/core/apps.py`
- Create: `tests/test_apps/test_core/test_apps.py`
- Modify: `server/settings/components/common.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_core/test_apps.py`:

```python
"""Tests for server/apps/core/apps.py."""

from unittest.mock import patch

from django.apps import apps


def test_core_config_ready_calls_init_sentry_and_init_logfire() -> None:
    """CoreConfig.ready() initialises Sentry and Logfire in order."""
    with (
        patch('server.apps.core.apps.init_sentry') as mock_sentry,
        patch('server.apps.core.apps.init_logfire') as mock_logfire,
    ):
        apps.get_app_config('core').ready()
    mock_sentry.assert_called_once_with()
    mock_logfire.assert_called_once_with()
```

- [ ] **Step 2: Run test — confirm it fails (app not registered yet)**

```bash
docker compose exec web pytest tests/test_apps/test_core/test_apps.py --no-cov -v
```

Expected: `LookupError: No installed app with label 'core'.`

- [ ] **Step 3: Create the core app package**

Create `server/apps/core/__init__.py` (empty file).

- [ ] **Step 4: Create `server/apps/core/apps.py`**

```python
"""Django application configuration for core infrastructure."""

from typing import override

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Permanent infrastructure app — initialises observability at startup."""

    name = 'server.apps.core'
    default = True

    @override
    def ready(self) -> None:
        """Initialise Sentry and Logfire once at Django startup."""
        from server.common.observability import init_logfire, init_sentry

        init_sentry()
        init_logfire()
```

- [ ] **Step 5: Register the app in INSTALLED_APPS**

In `server/settings/components/common.py`, add `'server.apps.core'` before `'server.apps.main'` in `INSTALLED_APPS`:

```python
INSTALLED_APPS: tuple[str, ...] = (
    # ... existing django apps and axes/unfold ...
    # Our apps:
    'server.apps.core',  # ← add this line
    'server.apps.main',
    # ... rest unchanged ...
)
```

- [ ] **Step 6: Run the test — confirm it passes**

```bash
docker compose exec web pytest tests/test_apps/test_core/test_apps.py --no-cov -v
```

Expected: 1 test PASSED.

- [ ] **Step 7: Verify Django system check still passes**

```bash
docker compose exec web python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Run lint and type check**

```bash
docker compose exec web ruff check server/apps/core/
docker compose exec web mypy server/apps/core/
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add server/apps/core/ tests/test_apps/test_core/ server/settings/components/common.py
git commit -m "feat(core): add infrastructure app that initialises observability at startup"
```

---

## Task 5: Taskiq Observability Middleware (TDD)

**Files:**
- Create: `server/common/taskiq_middleware.py`
- Create: `tests/test_server/test_taskiq_middleware.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server/test_taskiq_middleware.py`:

```python
"""Tests for server/common/taskiq_middleware.py."""

import asyncio
from unittest.mock import MagicMock, patch

from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

from server.common.taskiq_middleware import ObservabilityMiddleware, _span_stack


def _make_message(
    task_name: str = 'test_task',
    task_id: str = 'abc-123',
) -> TaskiqMessage:
    return TaskiqMessage(
        task_id=task_id,
        task_name=task_name,
        labels={},
        args=[],
        kwargs={},
    )


def _make_result() -> TaskiqResult[None]:
    return TaskiqResult(
        is_err=False,
        log='',
        return_value=None,
        execution_time=0.0,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_pre_execute_returns_message_unchanged() -> None:
    """pre_execute returns the same message object it receives."""
    middleware = ObservabilityMiddleware()
    message = _make_message()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch('logfire.span', return_value=mock_ctx):
        result = _run(middleware.pre_execute(message))
    assert result is message


def test_pre_execute_opens_logfire_span_with_task_context() -> None:
    """pre_execute calls logfire.span with the task name and ID."""
    middleware = ObservabilityMiddleware()
    message = _make_message(task_name='my_task', task_id='id-1')
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch('logfire.span', return_value=mock_ctx) as mock_span:
        _run(middleware.pre_execute(message))
    mock_span.assert_called_once_with(
        'task {task_name}',
        task_name='my_task',
        task_id='id-1',
    )


def test_post_execute_closes_span_and_returns_result() -> None:
    """post_execute closes the active ExitStack and returns result unchanged."""
    middleware = ObservabilityMiddleware()
    message = _make_message()
    result = _make_result()
    mock_stack = MagicMock()
    _span_stack.set(mock_stack)

    returned = _run(middleware.post_execute(message, result))

    mock_stack.close.assert_called_once()
    assert returned is result
    assert _span_stack.get() is None


def test_post_execute_handles_no_active_span() -> None:
    """post_execute is a no-op when no span was previously opened."""
    middleware = ObservabilityMiddleware()
    message = _make_message()
    result = _make_result()
    _span_stack.set(None)

    returned = _run(middleware.post_execute(message, result))

    assert returned is result


def test_on_error_captures_exception_to_sentry_with_task_tags() -> None:
    """on_error sends the exception to Sentry tagged with task name and ID."""
    middleware = ObservabilityMiddleware()
    message = _make_message(task_name='failing_task', task_id='id-2')
    result = _make_result()
    error = ValueError('task failed')
    mock_scope = MagicMock()

    with patch('sentry_sdk.new_scope') as mock_new_scope:
        mock_new_scope.return_value.__enter__ = MagicMock(
            return_value=mock_scope
        )
        mock_new_scope.return_value.__exit__ = MagicMock(return_value=False)
        _run(middleware.on_error(message, result, error))

    mock_scope.set_tag.assert_any_call('task_name', 'failing_task')
    mock_scope.set_tag.assert_any_call('task_id', 'id-2')
    mock_scope.capture_exception.assert_called_once_with(error)
```

> **Note on `TaskiqMessage` constructor:** If `TaskiqMessage` does not accept bare keyword args in Taskiq 0.11, inspect `taskiq.message.TaskiqMessage` first with `python -c "from taskiq.message import TaskiqMessage; help(TaskiqMessage)"` inside the container and adjust `_make_message` accordingly.

- [ ] **Step 2: Run tests — confirm they fail**

```bash
docker compose exec web pytest tests/test_server/test_taskiq_middleware.py --no-cov -v
```

Expected: `ImportError: cannot import name 'ObservabilityMiddleware'`

- [ ] **Step 3: Implement `server/common/taskiq_middleware.py`**

```python
"""Taskiq middleware for Sentry and Logfire observability."""

import contextlib
import contextvars
from typing import Any

import logfire
import sentry_sdk
from taskiq import TaskiqMiddleware
from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

_span_stack: contextvars.ContextVar[contextlib.ExitStack | None] = (
    contextvars.ContextVar('_span_stack', default=None)
)


class ObservabilityMiddleware(TaskiqMiddleware):
    """Wraps each Taskiq task with a Logfire span and Sentry error capture."""

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Open a Logfire span tagged with task name and ID."""
        stack = contextlib.ExitStack()
        stack.enter_context(
            logfire.span(
                'task {task_name}',
                task_name=message.task_name,
                task_id=message.task_id,
            ),
        )
        _span_stack.set(stack)
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> TaskiqResult[Any]:
        """Close the Logfire span on normal task completion."""
        stack = _span_stack.get()
        if stack is not None:
            stack.close()
            _span_stack.set(None)
        return result

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Capture the exception to Sentry with task name and ID as tags."""
        with sentry_sdk.new_scope() as scope:
            scope.set_tag('task_name', message.task_name)
            scope.set_tag('task_id', message.task_id)
            scope.capture_exception(exception)
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
docker compose exec web pytest tests/test_server/test_taskiq_middleware.py --no-cov -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Run lint and type check**

```bash
docker compose exec web ruff check server/common/taskiq_middleware.py
docker compose exec web mypy server/common/taskiq_middleware.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add server/common/taskiq_middleware.py tests/test_server/test_taskiq_middleware.py
git commit -m "feat(observability): add Taskiq middleware for Logfire spans and Sentry error capture"
```

---

## Task 6: Wire Middleware into the Broker

**Files:**
- Modify: `server/common/broker.py`

The Taskiq broker is created at module level. Adding `.with_middlewares()` attaches the middleware to every task run by all three processes (web, worker, scheduler). Both `logfire.span()` and `sentry_sdk.new_scope()` are no-ops before their respective `init` functions are called, so importing and attaching early is safe.

- [ ] **Step 1: Update `server/common/broker.py`**

Add the import and chain `.with_middlewares()` onto the broker:

```python
import os

from decouple import config
from taskiq import TaskiqEvents, TaskiqState
from taskiq_aio_pika import AioPikaBroker
from taskiq_redis import RedisAsyncResultBackend

from server.common.taskiq_middleware import ObservabilityMiddleware

broker = (
    AioPikaBroker(
        config('RABBITMQ_URL', default='amqp://guest:guest@localhost:5672/'),
    )
    .with_result_backend(
        RedisAsyncResultBackend(
            config('REDIS_URL', default='redis://localhost:6379'),
        ),
    )
    .with_middlewares(ObservabilityMiddleware())
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _setup_django(  # pragma: no cover  # noqa: RUF029
    _state: TaskiqState,
) -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
    import django  # noqa: PLC0415

    django.setup()
```

- [ ] **Step 2: Run the full test suite**

```bash
docker compose exec web pytest --no-cov
```

Expected: all tests pass. If the `_taskiq_in_memory` fixture in `tests/plugins/taskiq_broker.py` breaks because the swapped broker no longer has middleware registered, add `ObservabilityMiddleware` to `_NoOpBroker` or verify the fixture still works (the middleware won't be called on kicked messages in tests, only on executed ones).

- [ ] **Step 3: Run lint and type check**

```bash
docker compose exec web ruff check server/common/broker.py
docker compose exec web mypy server/common/broker.py
```

- [ ] **Step 4: Commit**

```bash
git add server/common/broker.py
git commit -m "feat(observability): wire ObservabilityMiddleware onto the Taskiq broker"
```

---

## Task 7: Document Env Vars and Run Full Checks

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add new env vars to `.env.example`**

Add a section to `.env.example`:

```dotenv
# --- Observability ---
# Sentry: leave empty to disable. Get DSN from https://sentry.io → Project Settings → Client Keys
SENTRY_DSN=
# 1.0 = trace every request (dev default). Lower in prod, e.g. 0.1
SENTRY_TRACES_SAMPLE_RATE=1.0
# Profiling sample rate (subset of traced requests). 0.1 in dev, 0.05 in prod
SENTRY_PROFILES_SAMPLE_RATE=0.1

# Logfire: leave empty to disable. Get token from https://logfire.pydantic.dev → Settings → Write Tokens
LOGFIRE_TOKEN=
# Distinguish dev vs prod data in Logfire dashboards
LOGFIRE_SERVICE_NAME=***REMOVED***
```

- [ ] **Step 2: Run the full test suite with coverage**

```bash
docker compose exec web pytest
```

Expected: all tests pass, coverage ≥ 100%.

- [ ] **Step 3: Run all linters and import checks**

```bash
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web mypy server
docker compose exec web lint-imports
```

Expected: all clean.

- [ ] **Step 4: Run migration checks**

```bash
docker compose exec web python manage.py check_migrations --exclude-apps=axes
docker compose exec web python manage.py lintmigrations
```

Expected: no issues (no new models were added).

- [ ] **Step 5: Commit**

```bash
git add .env.example
git commit -m "chore: document Sentry and Logfire env vars in .env.example"
```

---

## Verification

End-to-end smoke test (requires real credentials in `.env.local`):

1. Set `SENTRY_DSN`, `LOGFIRE_TOKEN`, `LOGFIRE_SERVICE_NAME=***REMOVED***-dev` in `.env.local`
2. `docker compose up -d` — start all services
3. **Web tracing:** hit any API endpoint and confirm a Logfire trace appears with a Django request span, SQL child spans, and Redis child spans
4. **Error capture:** add a temporary `raise ValueError('test')` to any view, hit the endpoint, confirm the error appears in Sentry with INFO-level structlog breadcrumbs showing the request path
5. **Task tracing:** trigger any task (e.g. `notify_blog_post_created`) and confirm a `task notify_blog_post_created` span appears in Logfire
6. **Task error capture:** force a task to raise, confirm Sentry receives it tagged with `task_name` and `task_id`
7. **Graceful degradation:** remove `SENTRY_DSN` from `.env.local`, restart web, confirm the app serves requests without error
