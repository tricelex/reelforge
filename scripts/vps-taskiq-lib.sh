#!/usr/bin/env bash
# Shared helpers for vps-taskiq-*.sh — not meant to be run directly.

_VPS_TASKIQ_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./vps-lib.sh
source "$_VPS_TASKIQ_LIB_DIR/vps-lib.sh"

TASKIQ_ASYNC_SERVICES=(scheduler worker-api worker-render)

taskiq_compose() {
  vps_compose "$@"
}

taskiq_stop_async() {
  echo "==> Stopping async services: ${TASKIQ_ASYNC_SERVICES[*]}"
  taskiq_compose stop "${TASKIQ_ASYNC_SERVICES[@]}"
}

taskiq_start_async() {
  local tag
  tag="$(vps_deployed_image_tag)"
  echo "==> Starting async services: ${TASKIQ_ASYNC_SERVICES[*]} (IMAGE_TAG=${tag})"
  taskiq_compose pull "${TASKIQ_ASYNC_SERVICES[@]}"
  taskiq_compose up -d "${TASKIQ_ASYNC_SERVICES[@]}"
  taskiq_compose ps "${TASKIQ_ASYNC_SERVICES[@]}"
}

taskiq_restart_async() {
  echo "==> Restarting async services: ${TASKIQ_ASYNC_SERVICES[*]}"
  taskiq_compose restart "${TASKIQ_ASYNC_SERVICES[@]}"
  taskiq_compose ps "${TASKIQ_ASYNC_SERVICES[@]}"
}

taskiq_print_queue_status() {
  vps_ssh "cd ${VPS_APP_DIR} && docker compose exec -T web python - <<'PY'
import asyncio

import aio_pika
from aio_pika.exceptions import ChannelNotFoundEntity
from decouple import config


async def main() -> None:
    url = config('RABBITMQ_URL', default='amqp://guest:guest@localhost:5672/')
    connection = await aio_pika.connect_robust(url)
    async with connection:
        for name in ('api', 'render'):
            channel = await connection.channel()
            try:
                declare_ok = await channel.declare_queue(name, passive=True)
                result = declare_ok.declaration_result
                print(
                    f'queue {name} exists messages={result.message_count} '
                    f'consumers={result.consumer_count}'
                )
            except ChannelNotFoundEntity:
                print(f'queue {name} missing messages=0 consumers=0')
            finally:
                await channel.close()


asyncio.run(main())
PY"
}

taskiq_delete_queues() {
  vps_ssh "cd ${VPS_APP_DIR} && docker compose exec -T web python - <<'PY'
import asyncio

import aio_pika
from aio_pika.exceptions import ChannelNotFoundEntity
from decouple import config


async def main() -> None:
    url = config('RABBITMQ_URL', default='amqp://guest:guest@localhost:5672/')
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        underlay = await channel.get_underlay_channel()
        for name in ('api', 'render'):
            try:
                result = await underlay.queue_delete(
                    queue=name,
                    if_unused=False,
                    if_empty=False,
                )
                print(
                    f'deleted {name}: message_count={result.message_count}'
                )
            except ChannelNotFoundEntity:
                print(f'queue missing: {name}')


asyncio.run(main())
PY"
}

taskiq_print_db_status() {
  vps_ssh "cd ${VPS_APP_DIR} && docker compose exec -T web python - <<'PY'
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
import django

django.setup()

from collections import Counter

from server.apps.pipelines.models import (
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)

ACTIVE_RUN_STATUSES = [
    RunStatus.PENDING,
    RunStatus.RUNNING,
    RunStatus.AWAITING_REVIEW,
    RunStatus.BUDGET_HOLD,
    RunStatus.PUBLISH_HOLD,
    RunStatus.PUBLISHING,
]
ACTIVE_STAGE_STATUSES = [
    StageStatus.PENDING,
    StageStatus.QUEUED,
    StageStatus.RUNNING,
    StageStatus.NEEDS_INPUT,
]

active_runs = PipelineRun.objects.filter(status__in=ACTIVE_RUN_STATUSES)
active_stages = StageExecution.objects.filter(status__in=ACTIVE_STAGE_STATUSES)
print('active_runs', active_runs.count())
print('active_stages', active_stages.count())
for status, count in Counter(
    active_runs.values_list('status', flat=True),
).items():
    print(f'run_status {status} {count}')
for status, count in Counter(
    active_stages.values_list('status', flat=True),
).items():
    print(f'stage_status {status} {count}')
for run in active_runs.order_by('-updated_at')[:5]:
    print(
        f'run {run.id} status={run.status} '
        f'updated={run.updated_at.isoformat()}',
    )
for stage in active_stages.select_related('run').order_by('-updated_at')[:10]:
    print(
        f'stage {stage.id} run={stage.run_id} key={stage.stage_key} '
        f'status={stage.status} updated={stage.updated_at.isoformat()}',
    )
PY"
}

taskiq_cancel_active_state() {
  vps_ssh "cd ${VPS_APP_DIR} && docker compose exec -T web python - <<'PY'
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
import django

django.setup()

from django.utils import timezone

from server.apps.pipelines.models import (
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)

now = timezone.now()
runs = PipelineRun.objects.filter(
    status__in=[
        RunStatus.PENDING,
        RunStatus.RUNNING,
        RunStatus.AWAITING_REVIEW,
        RunStatus.BUDGET_HOLD,
        RunStatus.PUBLISH_HOLD,
        RunStatus.PUBLISHING,
    ],
)
stages = StageExecution.objects.filter(
    status__in=[
        StageStatus.PENDING,
        StageStatus.QUEUED,
        StageStatus.RUNNING,
        StageStatus.NEEDS_INPUT,
    ],
)
print('runs_to_cancel', runs.count())
print('stages_to_cancel', stages.count())
runs.update(status=RunStatus.CANCELLED, finished_at=now)
stages.update(
    status=StageStatus.CANCELLED,
    finished_at=now,
    error={'reason': 'manual_queue_reset'},
)
print('cancelled_runs', runs.count())
print('cancelled_stages', stages.count())
PY"
}

taskiq_detect_stuck() {
  local output
  local queue_messages=0
  local active_runs=0
  local active_stages=0

  output="$(taskiq_print_queue_status 2>/dev/null || true)"
  if [ -n "$output" ]; then
    while IFS= read -r line; do
      if [[ "$line" =~ ^queue\ .*\ messages=([0-9]+) ]]; then
        queue_messages=$((queue_messages + BASH_REMATCH[1]))
      fi
    done <<< "$output"
  fi

  output="$(taskiq_print_db_status 2>/dev/null || true)"
  if [ -n "$output" ]; then
    while IFS= read -r line; do
      case "$line" in
        active_runs\ *)
          active_runs="${line#active_runs }"
          ;;
        active_stages\ *)
          active_stages="${line#active_stages }"
          ;;
      esac
    done <<< "$output"
  fi

  if [ "$queue_messages" -gt 0 ] || [ "$active_runs" -gt 0 ] || [ "$active_stages" -gt 0 ]; then
    return 1
  fi
  return 0
}
