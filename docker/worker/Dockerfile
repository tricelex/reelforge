# Multi-stage: Poetry + build tools stay in the builder; runtime is slim.
# ML group (mediapipe / scenedetect) only lives here.

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

# OpenCV (via mediapipe's opencv-contrib-python) needs X11/GL shared libs
# even for the builder smoke import.
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        libgl1 \
        libglib2.0-0 \
        libpq-dev \
        libsm6 \
        libxext6 \
        libxrender1 \
        libxcb1 \
    && curl -sSL 'https://install.python-poetry.org' | python - \
    && poetry --version \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml poetry.lock ./

# Install main + ml. mediapipe + scenedetect live here.
# mediapipe wheels are manylinux_2_28_x86_64 only — build with platform
# linux/amd64 (see docker-compose.worker.yml).
# NOTE: `--only main --with ml` does NOT install ml in Poetry 2.4 — use
# `--with ml` (main is always included) or `--only main,ml`.
RUN poetry sync --with ml --no-interaction --no-ansi \
    && python -c "import mediapipe; import cv2"

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
    DJANGO_ENV=production \
    MEDIAPIPE_FACE_MODEL_PATH=/opt/mediapipe/blaze_face_short_range.tflite

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# ffmpeg: video/audio extraction ahead of ElevenLabs Scribe hosted-API upload.
# libgl1 / libglib / libxcb*: OpenCV (opencv-contrib-python via mediapipe).
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        bash \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libxcb1 \
        unzip \
    && mkdir -p /opt/mediapipe \
    && curl -fsSL \
        'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite' \
        -o /opt/mediapipe/blaze_face_short_range.tflite \
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
    && chown web:web -R '/code' \
    && chown -R web:web /opt/mediapipe

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
