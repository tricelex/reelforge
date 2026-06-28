"""Tests for dump_openapi_schema management command."""

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_dump_openapi_schema_stdout() -> None:
    """Command writes OpenAPI YAML to stdout."""
    call_command('dump_openapi_schema')


@pytest.mark.django_db
def test_dump_openapi_schema_to_file(tmp_path: object) -> None:
    """Command can write OpenAPI YAML to a file."""
    out = tmp_path / 'schema.yaml'  # type: ignore[operator]
    call_command('dump_openapi_schema', output=str(out))
    text = out.read_text(encoding='utf-8')
    assert 'openapi:' in text
    assert '/api/candidates/' in text
