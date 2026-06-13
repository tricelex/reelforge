import pytest

from server.apps.main.models import BlogPost


@pytest.fixture
def main_heading() -> str:
    """An example fixture containing some html fragment."""
    return 'data-testid="wemake-django-template"'


@pytest.fixture
def blog_post(db: None) -> BlogPost:
    """A persisted BlogPost instance for use in task tests."""
    return BlogPost.objects.create(title='Test Post', body='Test body')
