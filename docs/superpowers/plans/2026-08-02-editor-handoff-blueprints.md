# Editor Handoff Blueprints Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or
> execute task-by-task. Steps use checkbox syntax.

**Goal:** Four editor-handoff blueprints ending in a zip package + frontend
Download/Rebuild UX.

**Architecture:** Reuse existing spines; swap assembly/publish (or
clip_render/distribute) for handoff stages that build docs, markers, captions,
and a zip (`AssetKind.PACKAGE`). Clipping packages omit preview renders.

**Tech Stack:** Django 6 / punq / DMR / msgspec / ffmpeg / React (orval).

## Global Constraints

- Python 3.13, Django 6, ruff 80-col single quotes, mypy strict, 100% coverage
- No `from __future__ import annotations` in punq-registered files
- Zero-downtime migrations

## Tasks

### Task 1: AssetKind.PACKAGE + handoff helpers + seed graphs

- [ ] Add `PACKAGE` to `AssetKind`, migration updating check constraint
- [ ] Add `is_editor_handoff_blueprint(name|snapshot)` helper
- [ ] Seed four `*_editor_*` graphs in `seed_blueprints.py`
- [ ] Register new stage modules in `stages/__init__.py`
- [ ] Tests for seed keys / no assembly-publish on editor graphs

### Task 2: Handoff stages

- [ ] `editor_brief`, `timeline_export`, `caption_bundle`
- [ ] `package_zip` (layout + MANIFEST + zip asset; no clipping previews)
- [ ] Unit tests per stage

### Task 3: Package API

- [ ] Value objects + service methods
- [ ] GET package / POST rebuild-package controllers + urls
- [ ] API tests

### Task 4: Frontend

- [ ] Sync OpenAPI → orval
- [ ] Blueprint labels + Download/Rebuild on run detail
- [ ] Hide Publish for handoff runs
