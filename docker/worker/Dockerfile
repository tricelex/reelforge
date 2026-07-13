# Multi-stage: Poetry + build tools stay in the builder; runtime is slim.
# ML group (torch / whisperx / scenedetect) only lives in this image.

ARG PYTHON_IMAGE=python:3.13.13-slim-bookworm

# ---------------------------------------------------------------------------
# Builder — install Python deps (main + ml)
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

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

# Install main + ml. torch + CUDA + whisperx + scenedetect only live here.
# NOTE: `--only main --with ml` does NOT install ml in Poetry 2.4 — use
# `--with ml` (main is always included) or `--only main,ml`.
RUN poetry sync --with ml --no-interaction --no-ansi \
    && python -c "import whisperx"

# ---------------------------------------------------------------------------
# Runtime — no Poetry, no compilers
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG UID=1000
ARG GID=1000

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/code \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    DJANGO_ENV=production

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# ffmpeg: video processing. libsndfile1: speechbrain / soundfile audio I/O.
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        bash \
        curl \
        ffmpeg \
        libpq5 \
        libsndfile1 \
        unzip \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages \
    /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# deno: yt-dlp JavaScript runtime — install after COPY so builder bins
# do not overwrite /usr/local/bin/deno.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /code

RUN groupadd -g "${GID}" -r web \
    && useradd -d '/code' -g web -l -r -u "${UID}" web \
    && chown web:web -R '/code'

COPY --chown=web:web . /code

USER web

CMD ["python", "-m", "taskiq", "worker", \
     "server.common.broker:broker", \
     "server.common.django_setup", \
     "server.apps.main.tasks", \
     "server.apps.assets.tasks", \
     "server.apps.clips.tasks", \
     "server.apps.pipelines.tasks", \
     "server.apps.analytics.tasks"]
