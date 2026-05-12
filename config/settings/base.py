# ruff: noqa: ERA001
"""Base settings to build other settings files upon."""

import ssl
from datetime import timedelta
from pathlib import Path

import environ
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from kombu import Queue

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# ***REMOVED***/
APPS_DIR = BASE_DIR / "***REMOVED***"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "UTC"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#languages
# from django.utils.translation import gettext_lazy as _
# LANGUAGES = [
#     ('en', _('English')),
#     ('fr-fr', _('French')),
#     ('pt-br', _('Portuguese')),
# ]
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.forms",
]
THIRD_PARTY_APPS = [
    # Unfold must come before django.contrib.admin
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "unfold.contrib.import_export",
    "unfold.contrib.guardian",
    "unfold.contrib.simple_history",
    "unfold.contrib.location_field",
    "unfold.contrib.constance",
    # Django admin after Unfold
    "django.contrib.admin",
    # Other third-party apps
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    "django_celery_beat",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "django_fsm",
    "django_fsm_log",
    "django_htmx",
]

LOCAL_APPS = [
    "***REMOVED***.users",
    "***REMOVED***.core",
    "***REMOVED***.channels",
    "***REMOVED***.pipeline",
    "***REMOVED***.research",
    "***REMOVED***.scripts",
    "***REMOVED***.assets",
    "***REMOVED***.production",
    "***REMOVED***.distribution",
    "***REMOVED***.ai",
    "***REMOVED***.clipping",
    "***REMOVED***.ui",
    # Note: ***REMOVED***.services is a utility module, not a Django app
    # Your stuff: custom apps go here
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "***REMOVED***.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "***REMOVED***.users.context_processors.allauth_settings",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [("""Chuckz Okoye""", "chuckzokoye@gmail.com")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS
# https://cookiecutter-django.readthedocs.io/en/latest/settings.html#other-environment-settings
# Force the `admin` sign in process to go through the `django-allauth` workflow
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
REDIS_SSL = REDIS_URL.startswith("rediss://")

# PyAnnote speaker diarization model — required for Phase 2 ML analysis
HUGGINGFACE_TOKEN: str = env("HUGGINGFACE_TOKEN", default="")

# Celery
# ------------------------------------------------------------------------------
if USE_TZ:
    # https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-timezone
    CELERY_TIMEZONE = TIME_ZONE
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_SSL else None
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_backend
CELERY_RESULT_BACKEND = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_REDIS_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-extended
CELERY_RESULT_EXTENDED = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-always-retry
# https://github.com/celery/celery/pull/6122
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-max-retries
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
# No global time limits — set per-task where needed (e.g. render_clip has time_limit=1800)
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-send-task-events
CELERY_WORKER_SEND_TASK_EVENTS = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-task_send_sent_event
CELERY_TASK_SEND_SENT_EVENT = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-hijack-root-logger
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = (
    Queue("default"),
    Queue("orchestration"),
    Queue("research"),
    Queue("rendering"),
    Queue("uploads"),
    Queue("analytics"),
    Queue("clipping"),
)
CELERY_TASK_ROUTES = {
    "***REMOVED***.pipeline.tasks.render_video": {"queue": "rendering"},
    "***REMOVED***.pipeline.tasks.run_video_qa": {"queue": "rendering"},
    "***REMOVED***.pipeline.tasks.upload_video": {"queue": "uploads"},
    "***REMOVED***.pipeline.tasks.sync_channel_analytics": {"queue": "analytics"},
    "***REMOVED***.clipping.tasks.*": {"queue": "clipping"},
    "*": {"queue": "default"},
}
# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_LOGIN_METHODS = {"email"}
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_ADAPTER = "***REMOVED***.users.adapters.AccountAdapter"
# https://docs.allauth.org/en/latest/account/forms.html
ACCOUNT_FORMS = {"signup": "***REMOVED***.users.forms.UserSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_ADAPTER = "***REMOVED***.users.adapters.SocialAccountAdapter"
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_FORMS = {"signup": "***REMOVED***.users.forms.UserSocialSignupForm"}

# django-rest-framework
# -------------------------------------------------------------------------------
# django-rest-framework - https://www.django-rest-framework.org/api-guide/settings/
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",  # keep for browsable API / admin
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# djangorestframework-simplejwt
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=120),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# django-cors-headers - https://github.com/adamchainz/django-cors-headers#setup
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# By Default swagger ui is available only to admin user(s). You can change permission classes to change that
# See more configuration options at https://drf-spectacular.readthedocs.io/en/latest/settings.html#settings
SPECTACULAR_SETTINGS = {
    "TITLE": "ReelForge API",
    "DESCRIPTION": "Documentation of API endpoints of ReelForge",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SCHEMA_PATH_PREFIX": "/api/",
    "ENUM_GENERATE_CHOICE_DESCRIPTION": True,
    "ENUM_NAME_OVERRIDES": {
        # Status enums — each distinct choice set gets an explicit name to avoid hash-suffixed collisions
        "ChannelStatusEnum": "***REMOVED***.channels.choices.ChannelStatus",
        "AssetStatusEnum": "***REMOVED***.assets.models.AssetStatusChoices",
        "ClippingJobStatusEnum": "***REMOVED***.clipping.models.ClippingJob.Status",
        "ClipCandidateStatusEnum": "***REMOVED***.clipping.models.ClipCandidate.CandidateStatus",
        "ClipRenderStatusEnum": "***REMOVED***.clipping.models.ClipRender.RenderStatus",
        "ClipPostStatusEnum": "***REMOVED***.clipping.models.ClipPost.PostStatus",
        "ClipRenderStageStatusEnum": "***REMOVED***.clipping.models.ClipRenderStageResult.Status",
        # Shared enums that appear on multiple serializers — canonical names prevent duplicate-name warnings
        "ClipFormatEnum": "***REMOVED***.clipping.models.ClipRender.Format",
        "HookAnimationEnum": "***REMOVED***.clipping.constants.CaptionAnimation",
        "OutroTransitionEnum": "***REMOVED***.clipping.constants.TransitionStyle",
        "OverlayTypeEnum": "***REMOVED***.clipping.models.ClipTimedOverlay.OverlayType",
    },
}
# Your stuff...
# ------------------------------------------------------------------------------
######################################################################
# Unfold
######################################################################
UNFOLD = {
    "STUDIO": {
        # "header_sticky": True,
        # "layout_style": "boxed",
        # "header_variant": "dark",
        # "sidebar_style": "minimal",
        # "sidebar_variant": "dark",
        # "site_banner": "Custom global message",
    },
    "SITE_TITLE": _("Reelforge HQ"),
    "SITE_HEADER": _("Reelforge"),
    "SITE_SUBHEADER": _("Multi-Channel YouTube Automation"),
    "SITE_SYMBOL": "movie_creation",
    # "SITE_ICON": lambda request: static("images/logo.svg"),
    # "SITE_URL": None,
    "SITE_DROPDOWN": [
        {
            "icon": "api",
            "title": _("API Documentation"),
            "link": "/api/schema/swagger/",
        },
        {
            "icon": "monitor_heart",
            "title": _("Celery Flower"),
            "link": "/flower/",
        },
        {
            "icon": "help",
            "title": _("Unfold Documentation"),
            "link": "https://unfoldadmin.com/docs/",
        },
    ],
    "SHOW_HISTORY": True,
    # "SHOW_LANGUAGES": True,
    # "LANGUAGE_FLAGS": {
    #     "de": "🇩🇪",
    #     "en": "🇺🇸",
    # },
    # "ENVIRONMENT": "***REMOVED***.utils.environment_callback",  # Future: implement environment indicator
    # "DASHBOARD_CALLBACK": "***REMOVED***.views.dashboard_callback",  # Future: custom dashboard
    # "LOGIN": {
    #     "image": lambda request: static("images/login-bg.jpg"),
    # },
    "STYLES": [
        # lambda request: static("css/styles.css"),
    ],
    "SCRIPTS": [
        # lambda request: static("js/scripts.js"),
    ],
    # "TABS": [
    #     # Future: Add tabs for pipeline stages, channel management, etc.
    # ],
    # "COMMAND": {
    #     # Future: Custom search and history callbacks
    # },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "command_search": True,
        "navigation": [
            {
                "title": _("Core"),
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                ],
            },
            {
                "title": _("User Management"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "account_circle",
                        "link": reverse_lazy("admin:users_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
            {
                "title": _("Task Scheduling"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Periodic Tasks"),
                        "icon": "task",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_periodictask_changelist",
                        ),
                    },
                    {
                        "title": _("Crontabs"),
                        "icon": "update",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_crontabschedule_changelist",
                        ),
                    },
                    {
                        "title": _("Intervals"),
                        "icon": "timer",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_intervalschedule_changelist",
                        ),
                    },
                    {
                        "title": _("Clocked"),
                        "icon": "hourglass_bottom",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_clockedschedule_changelist",
                        ),
                    },
                    {
                        "title": _("Solar Events"),
                        "icon": "wb_sunny",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_solarschedule_changelist",
                        ),
                    },
                ],
            },
            {
                "title": _("Channel Management"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Channels"),
                        "icon": "video_library",
                        "link": reverse_lazy("admin:channels_channel_changelist"),
                    },
                    {
                        "title": _("Competitors"),
                        "icon": "trending_up",
                        "link": reverse_lazy("admin:channels_channelcompetitor_changelist"),
                    },
                    {
                        "title": _("Playlists"),
                        "icon": "playlist_play",
                        "link": reverse_lazy("admin:channels_channelplaylist_changelist"),
                    },
                ],
            },
            {
                "title": _("Pipeline"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Pipeline Runs"),
                        "icon": "account_tree",
                        "link": reverse_lazy("admin:pipeline_pipelinerun_changelist"),
                    },
                    {
                        "title": _("Pipeline Events"),
                        "icon": "event_note",
                        "link": reverse_lazy("admin:pipeline_pipelineevent_changelist"),
                    },
                ],
            },
            {
                "title": _("Content Production"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Research Jobs"),
                        "icon": "search",
                        "link": reverse_lazy("admin:research_researchjob_changelist"),
                    },
                    {
                        "title": _("Topic Ideas"),
                        "icon": "lightbulb",
                        "link": reverse_lazy("admin:research_topicidea_changelist"),
                    },
                    {
                        "title": _("Script Jobs"),
                        "icon": "description",
                        "link": reverse_lazy("admin:scripts_scriptjob_changelist"),
                    },
                    {
                        "title": _("Script Revisions"),
                        "icon": "history",
                        "link": reverse_lazy("admin:scripts_scriptrevision_changelist"),
                    },
                    {
                        "title": _("Asset Jobs"),
                        "icon": "perm_media",
                        "link": reverse_lazy("admin:assets_assetjob_changelist"),
                    },
                    {
                        "title": _("Scene Breakdown Jobs"),
                        "icon": "view_list",
                        "link": reverse_lazy("admin:production_scenebreakdownjob_changelist"),
                    },
                    {
                        "title": _("Audio Mix Jobs"),
                        "icon": "queue_music",
                        "link": reverse_lazy("admin:production_audiomixjob_changelist"),
                    },
                    {
                        "title": _("Production Jobs"),
                        "icon": "movie",
                        "link": reverse_lazy("admin:production_productionjob_changelist"),
                    },
                    {
                        "title": _("Distribution Jobs"),
                        "icon": "upload",
                        "link": reverse_lazy("admin:distribution_distributionjob_changelist"),
                    },
                ],
            },
            {
                "title": _("Asset Details"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Voiceover Segments"),
                        "icon": "record_voice_over",
                        "link": reverse_lazy("admin:assets_voiceoversegment_changelist"),
                    },
                    {
                        "title": _("Generated Images"),
                        "icon": "image",
                        "link": reverse_lazy("admin:assets_generatedimage_changelist"),
                    },
                    {
                        "title": _("Thumbnail Options"),
                        "icon": "photo_library",
                        "link": reverse_lazy("admin:assets_thumbnailoption_changelist"),
                    },
                ],
            },
            {
                "title": _("Generation Runs"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Voiceover Runs"),
                        "icon": "mic",
                        "link": reverse_lazy("admin:assets_voiceoverrun_changelist"),
                    },
                    {
                        "title": _("Image Generation Runs"),
                        "icon": "auto_awesome",
                        "link": reverse_lazy("admin:assets_imagegenerationrun_changelist"),
                    },
                    {
                        "title": _("Video Clip Generation Runs"),
                        "icon": "slow_motion_video",
                        "link": reverse_lazy("admin:assets_videoclipgenerationrun_changelist"),
                    },
                    {
                        "title": _("Thumbnail Runs"),
                        "icon": "crop_original",
                        "link": reverse_lazy("admin:assets_thumbnailrun_changelist"),
                    },
                ],
            },
            {
                "title": _("Analytics"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Analytics Snapshots"),
                        "icon": "analytics",
                        "link": reverse_lazy("admin:distribution_analyticssnapshot_changelist"),
                    },
                ],
            },
            {
                "title": _("Clipping"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Clipping Jobs"),
                        "icon": "content_cut",
                        "link": reverse_lazy("admin:clipping_clippingjob_changelist"),
                    },
                    {
                        "title": _("Clip Candidates"),
                        "icon": "movie",
                        "link": reverse_lazy("admin:clipping_clipcandidate_changelist"),
                    },
                    {
                        "title": _("Clip Posts"),
                        "icon": "share",
                        "link": reverse_lazy("admin:clipping_clippost_changelist"),
                    },
                ],
            },
        ],
    },
}

UNFOLD_STUDIO_ENABLE_CUSTOMIZER = True

UNFOLD_STUDIO_DEFAULT_FRAGMENT = "color-schemes"

UNFOLD_STUDIO_ENABLE_SAVE = False

UNFOLD_STUDIO_ENABLE_FILEUPLOAD = False

UNFOLD_STUDIO_ALWAYS_OPEN = True

UNFOLD_STUDIO_ENABLE_RESET_PASSWORD = True

# AI PROVIDER CONFIGURATION
# ------------------------------------------------------------------------------
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")

# Per-agent model strings — PydanticAI resolves "openai:*" and "anthropic:*" natively
RESEARCH_AGENT_MODEL      = env("RESEARCH_AGENT_MODEL",      default="openai:gpt-4o")
SCRIPT_AGENT_MODEL        = env("SCRIPT_AGENT_MODEL",        default="openai:gpt-4o")
VISUAL_PLANNER_MODEL      = env("VISUAL_PLANNER_MODEL",      default="openai:gpt-4o")
CLIP_ANALYSIS_MODEL       = env("CLIP_ANALYSIS_MODEL",       default="anthropic:claude-sonnet-4-5")
CAPTION_TRANSLATION_MODEL = env("CAPTION_TRANSLATION_MODEL", default="anthropic:claude-sonnet-4-5")

# Provider Defaults (TTS, image, video — unchanged)
DEFAULT_TTS_PROVIDER        = env("DEFAULT_TTS_PROVIDER",        default="elevenlabs")
DEFAULT_IMAGE_PROVIDER      = env("DEFAULT_IMAGE_PROVIDER",      default="fal_ai")
DEFAULT_VIDEO_CLIP_PROVIDER = env("DEFAULT_VIDEO_CLIP_PROVIDER", default="fal_ai_kling")

# EXTERNAL SERVICES (OPTIONAL)
# ------------------------------------------------------------------------------
# TTS Providers
ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY", default="")

# Image Generation Providers
FAL_API_KEY = env("FAL_KEY", default="")
REPLICATE_API_KEY = env("REPLICATE_API_KEY", default="")

# SerpAPI (YouTube search, Google Trends, Google Search)
SERPAPI_API_KEY = env("SERPAPI_API_KEY", default="")

# Tavily AI search (primary web_search provider)
TAVILY_API_KEY = env("TAVILY_API_KEY", default="")


# === API Keys ===
YOUTUBE_OAUTH_CLIENT_CONFIG = {
    "web": {
        "client_id": env("YOUTUBE_OAUTH_CLIENT_ID", default=""),
        "project_id": "***REMOVED***-488122",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": env("YOUTUBE_OAUTH_CLIENT_SECRET", default=""),
        "redirect_uris": ["http://localhost:8000/oauth/youtube/callback/"],
    }
}

CREDENTIAL_ENCRYPTION_KEY = env("CREDENTIAL_ENCRYPTION_KEY")
