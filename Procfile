web: uv run python manage.py runserver_plus 0.0.0.0:8000
worker: uv run celery -A config.celery_app worker -l INFO -Q default,orchestration,research,clipping,rendering,uploads,analytics
beat: rm -f celerybeat.pid && uv run celery -A config.celery_app beat -l INFO
flower: uv run celery -A config.celery_app -b "${REDIS_URL}" flower --basic_auth="${CELERY_FLOWER_USER}:${CELERY_FLOWER_PASSWORD}"
