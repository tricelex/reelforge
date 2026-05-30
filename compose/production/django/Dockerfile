
# define an alias for the specific python version used in this file.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-build-stage

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0

ARG APP_HOME=/app

WORKDIR ${APP_HOME}

# Install apt packages
RUN apt-get update && apt-get install --no-install-recommends -y \
  # dependencies for building Python packages
  build-essential \
  # psycopg dependencies
  libpq-dev


# Requirements are installed here to ensure they will be cached.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY . ${APP_HOME}

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev

# Pre-download pyannote speaker diarization model into /app/.cache/huggingface so the
# COPY below carries it into the run stage. No token is needed at runtime.
#
# Before running: accept gated model terms on HuggingFace (one-time):
#   https://hf.co/pyannote/speaker-diarization-community-1
#   https://hf.co/pyannote/segmentation-3.0
#   Then create a read token at https://hf.co/settings/tokens
#
# Build with:
#   DOCKER_BUILDKIT=1 docker build --secret id=hf_token,env=HUGGINGFACE_TOKEN ...
RUN --mount=type=secret,id=hf_token \
    if [ -f /run/secrets/hf_token ]; then \
      HF_HOME=${APP_HOME}/.cache/huggingface uv run python -c " \
from pyannote.audio import Pipeline; \
import os; \
os.environ.setdefault('HF_HOME', '${APP_HOME}/.cache/huggingface'); \
Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=open('/run/secrets/hf_token').read().strip()); \
print('pyannote model cached'); \
"; fi

# Python 'run' stage
FROM python:3.13-slim-bookworm AS python-run-stage

ARG APP_HOME=/app

WORKDIR ${APP_HOME}

RUN addgroup --system django \
  && adduser --system --ingroup django django


# Install required system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
  # psycopg dependencies
  libpq-dev \
  # Translations dependencies
  gettext \
  # entrypoint
  wait-for-it \
  # audio/video processing
  ffmpeg \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*


COPY --chown=django:django ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint
RUN chmod +x /entrypoint


COPY --chown=django:django ./compose/production/django/start /start
RUN sed -i 's/\r$//g' /start
RUN chmod +x /start
COPY --chown=django:django ./compose/production/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker
RUN chmod +x /start-celeryworker


COPY --chown=django:django ./compose/production/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat
RUN chmod +x /start-celerybeat


COPY --chown=django:django ./compose/production/django/celery/flower/start /start-flower
RUN sed -i 's/\r$//g' /start-flower
RUN chmod +x /start-flower

# Copy the application from the builder
COPY --from=python-build-stage --chown=django:django ${APP_HOME} ${APP_HOME}

# make django owner of the WORKDIR directory as well.
RUN chown django:django ${APP_HOME}

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"
# Point HuggingFace Hub at the model weights baked into the image at build time.
ENV HF_HOME="/app/.cache/huggingface"

USER django

RUN DATABASE_URL="" \
  CREDENTIAL_ENCRYPTION_KEY="build-time-placeholder" \
  DJANGO_SETTINGS_MODULE="config.settings.test" \
  python manage.py compilemessages

ENTRYPOINT ["/entrypoint"]
