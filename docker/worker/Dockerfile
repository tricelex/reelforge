FROM python:3.13.13-slim-bookworm

ARG UID=1000
ARG GID=1000

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/code \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_ROOT_USER_ACTION=ignore \
    POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME=/usr/local \
    DJANGO_ENV=production

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# System dependencies — includes ffmpeg (required for video processing),
# libsndfile1 (required by speechbrain / soundfile for audio I/O), and
# deno (yt-dlp JavaScript runtime for YouTube extraction).
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
        libsndfile1 \
        unzip \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && curl -sSL 'https://install.python-poetry.org' | python - \
    && poetry --version \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

WORKDIR /code

RUN groupadd -g "${GID}" -r web \
    && useradd -d '/code' -g web -l -r -u "${UID}" web \
    && chown web:web -R '/code'

COPY --chown=web:web pyproject.toml poetry.lock ./

# Install main + ml groups. torch + CUDA + whisperx + scenedetect only live here.
RUN poetry sync --only main --with ml --no-interaction --no-ansi

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
