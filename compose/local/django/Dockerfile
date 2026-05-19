# define an alias for the specific python version used in this file.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python

# Python build stage
FROM python AS python-build-stage

ARG APP_HOME=/app

WORKDIR ${APP_HOME}

# we need to move the virtualenv outside of the $APP_HOME directory because it will be overriden by the docker compose mount
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_HTTP_TIMEOUT=120

# Install apt packages
RUN apt-get update && apt-get install --no-install-recommends -y \
  # dependencies for building Python packages
  build-essential \
  # psycopg dependencies
  libpq-dev \
  gettext \
  wait-for-it \
  # audio/video processing
  ffmpeg

# Requirements are installed here to ensure they will be cached.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock:rw \
    uv sync --no-install-project

COPY . ${APP_HOME}

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock:rw \
    uv sync

# Pre-download pyannote speaker diarization model weights into the image layer
# so the Celery worker never downloads at runtime. Requires a build secret.
#
# Before running: accept gated model terms on HuggingFace (one-time):
#   https://hf.co/pyannote/speaker-diarization-community-1
#   https://hf.co/pyannote/segmentation-3.0
#   Then create a read token at https://hf.co/settings/tokens
#
# Build with:
#   DOCKER_BUILDKIT=1 docker compose build --secret id=hf_token,env=HUGGINGFACE_TOKEN django
#
# Skip the --secret flag to build without diarization (pipeline falls back gracefully).
RUN --mount=type=secret,id=hf_token \
    if [ -f /run/secrets/hf_token ]; then \
      uv run python -c " \
from pyannote.audio import Pipeline; \
import os; \
Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=open('/run/secrets/hf_token').read().strip()); \
print('pyannote model cached'); \
"; fi

# devcontainer dependencies and utils
RUN apt-get update && apt-get install --no-install-recommends -y \
  sudo git bash-completion nano ssh

# Create devcontainer user and add it to sudoers
RUN groupadd --gid 1000 dev-user \
  && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
  && echo dev-user ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/dev-user \
  && chmod 0440 /etc/sudoers.d/dev-user

ENV PATH="/${APP_HOME}/.venv/bin:$PATH"
ENV PYTHONPATH="${APP_HOME}/.venv/lib/python3.13/site-packages:$PYTHONPATH"

COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/local/django/start /start
RUN sed -i 's/\r$//g' /start
RUN chmod +x /start


COPY ./compose/local/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./compose/local/django/celery/worker/debug /start-celeryworker-debug
RUN sed -i 's/\r$//g' /start-celeryworker-debug
RUN chmod +x /start-celeryworker-debug

COPY ./compose/local/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat
RUN chmod +x /start-celerybeat

COPY ./compose/local/django/celery/flower/start /start-flower
RUN sed -i 's/\r$//g' /start-flower
RUN chmod +x /start-flower


ENTRYPOINT ["/entrypoint"]
