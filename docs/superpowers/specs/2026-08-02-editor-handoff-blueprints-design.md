# Editor Handoff Blueprints Design

Date: 2026-08-02  
Status: Approved

## Goal

Add parallel pipeline blueprints that produce a **downloadable zip package**
for a professional video editor (DaVinci Resolve), instead of auto-assembly
and YouTube publish.

## Decisions

- Shared terminal stages + four additive blueprint graphs
- Longform: full assets through motion / footage_prep, then package
- Clipping: candidates + markers + captions; no source video in zip; no CapCut
  `clip_render` / `clip_distribute`; no `clip_preview_render` in handoff graphs
- Auto-package on success; rebuild via rerun from `editor_brief`
- Blueprints: `longform_editor_v1`, `longform_doc_editor_v1`,
  `clipping_editor_v1`, `clipping_editor_manual_v1`
- Resolve interchange v1: CSV + EDL + SRT only (no `.drp`, no FCPXML)
- Frontend in `reelforge-frontend` is in scope
- Do not change `BLUEPRINT_BY_KIND` defaults

## Terminal stages

`editor_brief` (LLM editorial front matter + deterministic appendix)
→ `timeline_export` → `caption_bundle` → `package_zip`

`editor_brief` uses a pydantic-ai agent (`EditorBriefOutput`) for tone,
pacing, must-hit beats, caption/music guidance, and Resolve do/don'ts, then
appends exact chapters/scenes/candidates facts so rebuild stays grounded.

## Package layouts

See implementation plan. Longform VO is master timeline. Clipping omits source.

## API

- `GET /api/runs/{id}/package/`
- `POST /api/runs/{id}/rebuild-package/`

## Non-goals

`.drp` / FCPXML / AAF, auto-publish on editor blueprints, shipping clipping
source master, replacing existing auto-publish blueprints.
