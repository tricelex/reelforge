"""Tests for the main app management commands."""

from unittest.mock import patch

import pytest
from django.core.management import call_command


def test_trigger_test_task_enqueues_add(capsys: pytest.CaptureFixture[str]) -> None:
    """trigger_test_task calls kiq_task(add, 5, 3) and prints a success message."""
    with patch('server.apps.main.management.commands.trigger_test_task.kiq_task') as mock_kiq:
        call_command('trigger_test_task')

    from server.apps.main.tasks import add

    mock_kiq.assert_called_once_with(add, 5, 3)
    captured = capsys.readouterr()
    assert 'Task enqueued' in captured.out
