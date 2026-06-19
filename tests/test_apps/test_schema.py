import logging
from collections.abc import Iterator
from typing import Any

import pytest
import schemathesis as st
from django.conf import LazySettings
from django.urls import reverse
from schemathesis.specs.openapi.schemas import OpenApiSchema

from server.wsgi import application


@pytest.fixture(autouse=True)
def _schema_test_settings(settings: LazySettings) -> Iterator[None]:
    """Reduce noise and avoid axes lockouts during fuzzing."""
    settings.DQC_ENABLED = False
    settings.AXES_ENABLED = False
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def api_schema(
    transactional_db: None,
) -> 'OpenApiSchema':
    """Load OpenAPI schema as a pytest fixture."""
    return st.openapi.from_wsgi(reverse('openapi_json'), application)


schema = (
    st.pytest
    .from_fixture('api_schema')
    .include(
        path='/api/auth/me',
    )
    .include(
        path='/api/enums/',
    )
    .include(
        method='GET',
        path='/api/dashboard/',
    )
)


def _apply_auth_headers(
    case: st.Case[Any],
    auth_headers: dict[str, str],
) -> None:
    """Merge auth headers, defaulting when schemathesis omits headers."""
    if case.headers is None:
        case.headers = {}
    case.headers.update(auth_headers)


@pytest.mark.timeout(60)
@schema.parametrize()
def test_schemathesis(
    auth_headers: dict[str, str],
    *,
    case: st.Case[Any],
) -> None:
    """Ensure core authenticated API responses match the OpenAPI schema."""
    _apply_auth_headers(case, auth_headers)
    case.call_and_validate()


def test_apply_auth_headers_defaults_none() -> None:
    """Cover header defaulting when schemathesis omits headers."""
    from unittest.mock import MagicMock

    case = MagicMock()
    case.headers = None
    _apply_auth_headers(case, {'Authorization': 'Bearer token'})
    assert case.headers == {'Authorization': 'Bearer token'}
