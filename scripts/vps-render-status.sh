#!/usr/bin/env bash
# Snapshot of what worker-render is actually doing right now — built for
# "is this stuck, or just a slow ffmpeg encode?" checks during long
# ffmpeg-heavy stages (assembly, clip_render, etc.). Combines:
#   - the deployed image tag (confirms which commit is actually running)
#   - recent pipeline stage-lifecycle log events (started/succeeded/failed/...)
#   - one-shot container CPU/mem usage (docker stats)
#   - any live ffmpeg process inside the container, with elapsed time and a
#     best-guess phase label, via `docker top` (works even though the worker
#     image has no `ps` binary — `docker exec ... ps aux` will fail there)
#
# Usage:
#   ./scripts/vps-render-status.sh                  # last 200 log lines
#   ./scripts/vps-render-status.sh --log-lines 500   # more log context
#   ./scripts/vps-render-status.sh --since 30m       # logs from the last 30m instead of a line count
#   ./scripts/vps-render-status.sh --raw-logs        # also print the full raw log tail at the end

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-lib.sh
source ./vps-lib.sh

LOG_LINES=200
LOG_SINCE=''
SHOW_RAW_LOGS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --log-lines)
      LOG_LINES="$2"
      shift 2
      ;;
    --since)
      LOG_SINCE="$2"
      shift 2
      ;;
    --raw-logs)
      SHOW_RAW_LOGS=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--log-lines N] [--since 30m] [--raw-logs]" >&2
      exit 1
      ;;
  esac
done

hr() { printf '%s\n' '------------------------------------------------------------------------------'; }
section() {
  echo
  hr
  echo "== $1 =="
  hr
}

if [ -n "$LOG_SINCE" ]; then
  LOG_FETCH_ARGS=(--since "$LOG_SINCE")
  LOG_FETCH_DESC="since ${LOG_SINCE}"
else
  LOG_FETCH_ARGS=(--tail="$LOG_LINES")
  LOG_FETCH_DESC="last ${LOG_LINES} lines"
fi

section 'deployed image'
IMAGE_TAG="$(vps_deployed_image_tag)"
echo "IMAGE_TAG=${IMAGE_TAG}"
vps_ssh "cd ${VPS_APP_DIR} && docker compose ps worker-render"

CONTAINER_ID="$(vps_ssh "cd ${VPS_APP_DIR} && docker compose ps -q worker-render")"
if [ -z "$CONTAINER_ID" ]; then
  echo
  echo "worker-render is not running — nothing else to check." >&2
  exit 1
fi

# Pull the log window once, remotely, and reuse it for every section below —
# avoids re-fetching over SSH per section.
LOG_TEXT="$(vps_ssh "cd ${VPS_APP_DIR} && docker compose logs ${LOG_FETCH_ARGS[*]} worker-render" 2>/dev/null || true)"

section "recent stage events (${LOG_FETCH_DESC})"
STAGE_EVENTS="$(printf '%s\n' "$LOG_TEXT" | grep -E "event='(stage_started|stage_succeeded|stage_failed|stage_needs_input|stage_skipped_cancelled|stage_execution_duplicate_delivery|stage_cache_hit)'" | sed -E 's/^[a-zA-Z0-9_-]+ *\| *//' || true)"
if [ -z "$STAGE_EVENTS" ]; then
  echo "(no stage lifecycle events in this window — widen with --log-lines or --since)"
else
  printf '%s\n' "$STAGE_EVENTS"
fi

section 'container resource usage (one-shot)'
vps_ssh "docker stats --no-stream ${CONTAINER_ID}"

section 'live ffmpeg process(es)'
FFMPEG_PROCS="$(vps_ssh "docker top ${CONTAINER_ID} -eo pid,etime,pcpu,cmd 2>/dev/null | grep -i ffmpeg" || true)"
if [ -z "$FFMPEG_PROCS" ]; then
  echo "(none running right now — idle between ffmpeg steps, waiting on I/O, or not currently rendering)"
else
  while IFS= read -r line; do
    # Best-guess phase label from the ffmpeg command's output path (last
    # whitespace-separated token) — matches server/apps/pipelines/stages/
    # assembly.py's temp filenames (vid_*/mezz_*/*_concat.mp4/final.mp4).
    out_path="${line##* }"
    case "$out_path" in
      */final.mp4) phase='final_pass (subtitles/loudnorm/watermark encode)' ;;
      */*_concat.mp4) phase='chapter concat + transition' ;;
      */mezz_*.mp4) phase='per-scene mux (mux_scene)' ;;
      *) phase='ffmpeg (unrecognized phase)' ;;
    esac
    echo "phase: ${phase}"
    echo "  ${line}"
  done <<< "$FFMPEG_PROCS"
fi

if [ "$SHOW_RAW_LOGS" -eq 1 ]; then
  section "raw worker-render logs (${LOG_FETCH_DESC})"
  printf '%s\n' "$LOG_TEXT"
fi

echo
