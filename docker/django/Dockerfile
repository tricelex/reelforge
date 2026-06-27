FROM python:3.13.13-slim-bookworm

ARG UID=1000
ARG GID=1000

# Python / pip / Poetry env
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_ROOT_USER_ACTION=ignore \
    POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME=/usr/local \
    DJANGO_ENV=production

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# System dependencies (ffmpeg required for video processing)
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        bash \
        brotli \
        build-essential \
        curl \
        ffmpeg \
        gettext \
        git \
        libpq-dev \
    && curl -sSL 'https://install.python-poetry.org' | python - \
    && poetry --version \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

WORKDIR /code

RUN groupadd -g "${GID}" -r web \
    && useradd -d '/code' -g web -l -r -u "${UID}" web \
    && chown web:web -R '/code'

# Copy lockfiles first so this layer is cached when only source changes
COPY --chown=web:web pyproject.toml poetry.lock ./

# Install production deps only
RUN poetry sync --only main --no-interaction --no-ansi

# Copy source (this layer invalidates on every code change)
COPY --chown=web:web . /code

USER web

EXPOSE 8000

# Default command for the web service.
# Worker and scheduler override this via their Railway service settings.
CMD ["gunicorn", "--config", "/code/docker/django/gunicorn_config.py", "server.wsgi"]
