# Task 11 verification report

## Status

The documentary-foundations changes are covered and their focused checks pass,
but the repository-wide gate is not green. The full suite finished with
1,704 passed, 5 failed, and 96.91% total coverage. The remaining failures and
coverage deficit are broad pre-existing/shared-state issues outside the
foundations scope.

## Coverage and tests

- Full command: `docker compose exec web pytest`
  - 1,709 collected; 1,704 passed; 5 failed.
  - Total coverage: 96.91% (reported as 97%), below the 100% gate.
  - All stock provider/cache foundations modules were omitted from the
    coverage report because they reached complete coverage.
  - Remaining failures:
    - two executor/coverage tests leaked unclosed external Redis connections;
    - `test_visual_prompts_run_returns_prompts` supplied `[]` as a run UUID;
    - `test_run_export_pipeline_uses_format_dimensions` supplied a non-string
      checksum;
    - one cache-topic executor test surfaced another unclosed Redis socket.
- Focused Task 11 regression command: 36 passed.
- Untouched compatibility proof:
  - `git diff main...HEAD` and `git log main..HEAD` produced no changes for
    `test_assembly.py`, `test_motion.py`, or `test_image_gen.py`.
  - Their focused run passed: 44 passed.
  - The whole pipelines directory remains baseline-red: 472 passed, 4 failed,
    1 error, due to unrelated Redis resource leaks, malformed test context,
    and shared-state behavior.

## Static verification

- `ruff check --no-fix .`: 125 existing errors. Exact Task 11 files: clean.
- `ruff format --check .`: 92 existing unformatted files. Exact Task 11 files:
  10/10 formatted.
- `mypy server`: 78 errors in 31 files, exactly the allowed baseline; no errors
  in stock foundations, blueprint profiles, assembly, motion, or ffmpeg.
- `lint-imports`: 3 existing broken contracts and 3 kept; no stock foundations
  module is named in a violation.
- `lintmigrations`: 12 existing erroneous migrations; new assets `0007` and
  channels `0008` are both `OK`.
- `check_migrations --exclude-apps=axes`: 9 existing errors, 118 warnings,
  26 info. New migrations introduce no reported error.

## Environment stabilization

`/tmp/***REMOVED***`, `/tmp/***REMOVED***/assets`, and `/tmp/clip_renders` were restored
to `web:web` ownership with user read/write access. The clip render fonts
directory was created for the test process.

## Openverse design correction

The design document now records the live-API finding: Openverse supports images
and audio, not video (`/v1/video/` and `/v1/videos/` return 404). Openverse
therefore supplies CC stills, while archive.org supplies archival video.

