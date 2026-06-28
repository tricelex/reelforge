# Gunicorn configuration file
# https://docs.gunicorn.org/en/stable/configure.html#configuration-file
# https://docs.gunicorn.org/en/stable/settings.html

import os

bind = f'0.0.0.0:{os.environ.get("PORT", "8000")}'
# Fixed count avoids OOM on cloud VMs where cpu_count() can return 30+ virtual
# cores, which would spawn 60+ workers and exhaust RAM before any request lands.
workers = int(os.environ.get('WEB_CONCURRENCY', 2))

max_requests = 2000
max_requests_jitter = 400

accesslog = '-'
chdir = '/code'
worker_tmp_dir = '/dev/shm'  # noqa: S108
