"""
Django settings for server project.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/topics/settings/

For the full list of settings and their config, see
https://docs.djangoproject.com/en/6.0/ref/settings/
"""

from typing import Any

from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from server.settings.components import BASE_DIR, config

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

SECRET_KEY = config('DJANGO_SECRET_KEY')

# Application definition:

INSTALLED_APPS: tuple[str, ...] = (
    # Standard Django apps must come before our apps.
    # Their admin.py files are loaded first by autodiscover(), which lets
    # our admin.py safely call admin.site.unregister() on their models.
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.***REMOVED***',
    # Security — must also precede our apps for the same admin reason:
    'axes',
    # Our apps come after auth/axes (so their admin.py loads first, allowing
    # us to call admin.site.unregister) but before unfold (so our templates
    # take precedence over Unfold's built-in admin/index.html):
    'server.apps.core',
    'server.apps.main',
    'server.apps.channels',
    'server.apps.prompts',
    'server.apps.assets',
    'server.apps.pipelines',
    'server.apps.generation',
    'server.apps.rendering',
    'server.apps.publishing',
    'server.apps.analytics',
    'server.apps.clips',
    'server.apps.ideas',
    # Unfold must come before django.contrib.admin:
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'unfold.contrib.inlines',
    'django_json_widget',
    # django-admin:
    'django.contrib.admin',
    'django.contrib.admindocs',
    # django-modern-rest:
    'dmr',
    'corsheaders',
    # Health checks:
    # You may want to enable other checks as well,
    # see: https://github.com/KristianOellegaard/django-health-check
    'health_check',
)

MIDDLEWARE: tuple[str, ...] = (
    # Keep recurring health-check pings out of Logfire traces:
    'server.common.observability.SuppressHealthCheckObservabilityMiddleware',
    # CORS:
    'corsheaders.middleware.CorsMiddleware',
    # Logging:
    'server.settings.components.logging.LoggingContextVarsMiddleware',
    # Content Security Policy:
    'csp.middleware.CSPMiddleware',
    # Django:
    'django.middleware.security.SecurityMiddleware',
    # django-permissions-policy
    'django_permissions_policy.PermissionsPolicyMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Axes:
    'axes.middleware.AxesMiddleware',
)

ROOT_URLCONF = 'server.urls'

WSGI_APPLICATION = 'server.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.***REMOVED***ql',
        'NAME': config('POSTGRES_DB'),
        'USER': config('POSTGRES_USER'),
        'PASSWORD': config('POSTGRES_PASSWORD'),
        'HOST': config('DJANGO_DATABASE_HOST'),
        'PORT': config('DJANGO_DATABASE_PORT', cast=int),
        'CONN_MAX_AGE': config('CONN_MAX_AGE', cast=int, default=60),
        'OPTIONS': {
            'connect_timeout': 10,
            'options': '-c statement_timeout=15000ms',
            'sslmode': config('DJANGO_DATABASE_SSLMODE', default='prefer'),
            # consider using 'isolation_level' set to 'serializable'
        },
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Cors headers Settings
CORS_ALLOWED_ORIGINS = [
    config('FRONTEND_URL', default='http://localhost:3000'),
    "https://***REMOVED***-frontend-production.up.railway.app",
]

CORS_ALLOWED_CREDENTIALS = True

# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

USE_I18N = True

LANGUAGES = (('en', _('English')),)

LOCALE_PATHS = ('locale/',)

USE_TZ = True
TIME_ZONE = 'UTC'


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
)


# Templates
# https://docs.djangoproject.com/en/6.0/ref/templates/api

TEMPLATES = [
    {
        'APP_DIRS': True,
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            # Contains plain text templates, like `robots.txt`:
            BASE_DIR.joinpath('server', 'common', 'django', 'templates'),
        ],
        'OPTIONS': {
            'context_processors': [
                # Default template context processors:
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.request',
            ],
        },
    },
]


# Media files
# Media root dir is commonly changed in production
# (see development.py and production.py).
# https://docs.djangoproject.com/en/6.0/topics/files/

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR.joinpath('media')


# Django authentication system
# https://docs.djangoproject.com/en/6.0/topics/auth/

AUTHENTICATION_BACKENDS = (
    'axes.backends.AxesBackend',
    'django.contrib.auth.backends.ModelBackend',
)

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]


# Security
# https://docs.djangoproject.com/en/6.0/topics/security/

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

X_FRAME_OPTIONS = 'DENY'

# https://docs.djangoproject.com/en/3.0/ref/middleware/#referrer-policy
# https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy
SECURE_REFERRER_POLICY = 'same-origin'

# https://github.com/adamchainz/django-permissions-policy#setting
PERMISSIONS_POLICY: dict[str, str | list[str]] = {}


# Django Unfold admin configuration:
# https://unfoldadmin.com/docs/configuration/
UNFOLD: dict[str, Any] = {
    'SITE_TITLE': 'ReelForge',
    'SITE_HEADER': 'ReelForge Admin',
    'SITE_URL': '/',
    'SITE_ICON': {
        'light': lambda request: staticfiles_storage.url(
            'main/images/favicon-32x32.png',
        ),
        'dark': lambda request: staticfiles_storage.url(
            'main/images/favicon-32x32.png',
        ),
    },
    'DASHBOARD_CALLBACK': 'server.apps.main.dashboard.dashboard_callback',
    'SIDEBAR': {
        'show_search': True,
        'show_all_applications': False,
        'navigation': [
            {
                'title': 'Content',
                'separator': False,
                'items': [
                    {
                        'title': 'Blog Posts',
                        'icon': 'article',
                        'link': reverse_lazy('admin:main_blogpost_changelist'),
                    },
                ],
            },
            {
                'title': 'Channels',
                'separator': True,
                'items': [
                    {
                        'title': 'Channels',
                        'icon': 'tv',
                        'link': reverse_lazy(
                            'admin:channels_channel_changelist',
                        ),
                    },
                    {
                        'title': 'Characters',
                        'icon': 'face',
                        'link': reverse_lazy(
                            'admin:channels_character_changelist',
                        ),
                    },
                    {
                        'title': 'Character Sessions',
                        'icon': 'history',
                        'link': reverse_lazy(
                            'admin:channels_charactergenerationsession_changelist',
                        ),
                    },
                    {
                        'title': 'Niche Configs',
                        'icon': 'tune',
                        'link': reverse_lazy(
                            'admin:channels_nicheconfig_changelist',
                        ),
                    },
                    {
                        'title': 'YouTube Credentials',
                        'icon': 'key',
                        'link': reverse_lazy(
                            'admin:channels_youtubecredential_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Ideation',
                'separator': True,
                'items': [
                    {
                        'title': 'Topic Ideas',
                        'icon': 'lightbulb',
                        'link': reverse_lazy(
                            'admin:ideas_topicidea_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Prompts',
                'separator': True,
                'items': [
                    {
                        'title': 'Prompt Templates',
                        'icon': 'psychology',
                        'link': reverse_lazy(
                            'admin:prompts_prompttemplate_changelist',
                        ),
                    },
                    {
                        'title': 'Story Formats',
                        'icon': 'auto_stories',
                        'link': reverse_lazy(
                            'admin:prompts_storyformat_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Assets',
                'separator': True,
                'items': [
                    {
                        'title': 'Library Assets',
                        'icon': 'photo_library',
                        'link': reverse_lazy(
                            'admin:assets_libraryasset_changelist',
                        ),
                    },
                    {
                        'title': 'Pipeline Assets',
                        'icon': 'storage',
                        'link': reverse_lazy(
                            'admin:assets_asset_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Pipelines',
                'separator': True,
                'items': [
                    {
                        'title': 'Blueprints',
                        'icon': 'schema',
                        'link': reverse_lazy(
                            'admin:pipelines_pipelineblueprint_changelist',
                        ),
                    },
                    {
                        'title': 'Runs',
                        'icon': 'play_circle',
                        'link': reverse_lazy(
                            'admin:pipelines_pipelinerun_changelist',
                        ),
                    },
                    {
                        'title': 'Stage Executions',
                        'icon': 'timeline',
                        'link': reverse_lazy(
                            'admin:pipelines_stageexecution_changelist',
                        ),
                    },
                    {
                        'title': 'Cost Records',
                        'icon': 'payments',
                        'link': reverse_lazy(
                            'admin:pipelines_costrecord_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Publishing',
                'separator': True,
                'items': [
                    {
                        'title': 'Publish Jobs',
                        'icon': 'cloud_upload',
                        'link': reverse_lazy(
                            'admin:publishing_publishjob_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Clips',
                'separator': True,
                'items': [
                    {
                        'title': 'Sources',
                        'icon': 'video_library',
                        'link': reverse_lazy(
                            'admin:clips_clipsource_changelist',
                        ),
                    },
                    {
                        'title': 'Candidates',
                        'icon': 'movie',
                        'link': reverse_lazy(
                            'admin:clips_clipcandidate_changelist',
                        ),
                    },
                    {
                        'title': 'Campaigns',
                        'icon': 'campaign',
                        'link': reverse_lazy(
                            'admin:clips_clipcampaign_changelist',
                        ),
                    },
                    {
                        'title': 'Posts',
                        'icon': 'send',
                        'link': reverse_lazy(
                            'admin:clips_clippost_changelist',
                        ),
                    },
                    {
                        'title': 'Earnings',
                        'icon': 'paid',
                        'link': reverse_lazy(
                            'admin:clips_earning_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Auth',
                'separator': True,
                'items': [
                    {
                        'title': 'Users',
                        'icon': 'person',
                        'link': reverse_lazy('admin:auth_user_changelist'),
                    },
                    {
                        'title': 'Groups',
                        'icon': 'group',
                        'link': reverse_lazy('admin:auth_group_changelist'),
                    },
                    {
                        'title': 'User Profiles',
                        'icon': 'badge',
                        'link': reverse_lazy(
                            'admin:core_userprofile_changelist',
                        ),
                    },
                ],
            },
            {
                'title': 'Security',
                'separator': True,
                'items': [
                    {
                        'title': 'Login Attempts',
                        'icon': 'lock',
                        'link': reverse_lazy(
                            'admin:axes_accessattempt_changelist',
                        ),
                    },
                ],
            },
        ],
    },
}


# Timeouts
# https://docs.djangoproject.com/en/6.0/ref/settings/#std:setting-EMAIL_TIMEOUT

EMAIL_TIMEOUT = 5

# YouTube Data API v3 OAuth credentials
YOUTUBE_CLIENT_ID: str = config('YOUTUBE_CLIENT_ID', default='')
YOUTUBE_CLIENT_SECRET: str = config('YOUTUBE_CLIENT_SECRET', default='')

# Provider API keys
OPENAI_API_KEY: str = config('OPENAI_API_KEY', default='')
HUGGINGFACE_TOKEN: str = config('HUGGINGFACE_TOKEN', default='')
