# Multi-stage: Poetry + build tools stay in the builder; runtime is slim.

ARG PYTHON_IMAGE=python:3.13.13-slim-bookworm

# ---------------------------------------------------------------------------
# Builder — install Python deps only
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

# Controls which Poetry groups are installed.
# Pass --build-arg DJANGO_ENV=development for dev images.
ARG DJANGO_ENV=production

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
    POETRY_HOME=/opt/poetry \
    PATH="/opt/poetry/bin:${PATH}"

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        libpq-dev \
    && curl -sSL 'https://install.python-poetry.org' | python - \
    && poetry --version \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml poetry.lock ./

# Dev: install main + dev groups. Prod: main only.
# ML group is never installed here — see docker/worker/Dockerfile.
RUN if [ "$DJANGO_ENV" = "production" ]; then \
      poetry sync --only main --no-interaction --no-ansi; \
    else \
      poetry sync --without ml --no-interaction --no-ansi; \
    fi

# ---------------------------------------------------------------------------
# Runtime — no Poetry, no compilers
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG UID=1000
ARG GID=1000
ARG DJANGO_ENV=production

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/code \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    DJANGO_ENV=${DJANGO_ENV}

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# ffmpeg: frame extract / video tooling via API paths.
# gettext: compilemessages on deploy. brotli: static compression helpers.
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        bash \
        brotli \
        curl \
        ffmpeg \
        gettext \
        libpq5 \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages \
    /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /code

RUN groupadd -g "${GID}" -r web \
    && useradd -d '/code' -g web -l -r -u "${UID}" web \
    && chown web:web -R '/code'

COPY --chown=web:web . /code

USER web

EXPOSE 8000

CMD ["gunicorn", "--config", "/code/docker/django/gunicorn_config.py", "server.wsgi"]
