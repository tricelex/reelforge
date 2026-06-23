import pytest
from django.conf import LazySettings


@pytest.fixture(autouse=True)
def _media_root(
    settings: LazySettings,
    tmpdir_factory: pytest.TempPathFactory,
) -> None:
    """Forces django to save media files into temp folder."""
    settings.MEDIA_ROOT = tmpdir_factory.mktemp('media', numbered=True)


@pytest.fixture(autouse=True)
def _file_storage(settings: LazySettings) -> None:
    """Replace S3 storage with local FileSystemStorage in tests.

    No MinIO service runs in the test environment, so S3 calls would time
    out. FileSystemStorage combined with the _media_root tmpdir gives the
    same semantics for everything tests need to verify.
    """
    settings.STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }


@pytest.fixture(autouse=True)
def _password_hashers(settings: LazySettings) -> None:
    """Forces django to use fast password hashers for tests."""
    settings.PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.MD5PasswordHasher',
    ]


@pytest.fixture(autouse=True)
def _auth_backends(settings: LazySettings) -> None:
    """Deactivates security backend from Axes app."""
    settings.AUTHENTICATION_BACKENDS = (
        'django.contrib.auth.backends.ModelBackend',
    )


@pytest.fixture(autouse=True)
def _debug(settings: LazySettings) -> None:
    """Sets proper DEBUG and TEMPLATE debug mode for coverage."""
    settings.DEBUG = False
    for template in settings.TEMPLATES:
        template['OPTIONS']['debug'] = True
