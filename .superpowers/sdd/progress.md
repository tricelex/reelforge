# Documentary Blueprint — SDD Progress Ledger

Branch: feat/documentary-blueprint (off docs/documentary-blueprint-design)
Plans (in order):
1. docs/superpowers/plans/2026-07-26-documentary-blueprint-foundations.md
2. docs/superpowers/plans/2026-07-26-documentary-blueprint-pipeline.md
3. docs/superpowers/plans/2026-07-26-documentary-blueprint-frontend.md

## Pre-flight decisions (2026-07-26)
- Provider fixtures: built from PUBLISHED DOCS, not live capture (user decision;
  concern raised that adapters would be unverified against real responses).
  Fixtures must be marked doc-derived. Verify against live APIs once
  PEXELS_API_KEY / PIXABAY_API_KEY are configured.
- Broad `except Exception` in pipeline Task 4 `_rank`: PLAN GOVERNS, keep it.
- FAL_KEY empty: AI fallback leg untestable end-to-end; unit tests mock it.

## Task log

### Environment baselines (measured 2026-07-26, all PRE-EXISTING)
- `mypy server`: 78 errors / 31 files. Bar = no new errors in touched files.
- `lint-imports`: 3 of 6 contracts broken, ~50 violating imports. Bar = new
  stage->client imports declared; no new violation in touched files.
- `.git/hooks/pre-commit` is not executable, so it never runs.
- Removed one dead `.importlinter` entry (alignment -> whisperx client, deleted
  when transcription moved to ElevenLabs).

### Task log
- Task F1: complete (commit 1f3720a, review APPROVED)
  Minor findings deferred to final review:
  * no test exercises the non-dict `roles` defensive branch in resolve_role
  * report's justification for the doctest reformat was imprecise (cosmetic)
- Task F2: complete (commits 132411f + fix c802431, review APPROVED)
  Important finding FIXED: documentary path had no DB-level test; added
  test_build_scene_asset_map_queries_footage_prep_children (27/27 pass).
  Minor deferred: `blueprint_snapshot or {}` guard is redundant (harmless,
  matches existing precedent in selectors.py).

### LANDMINE for all agents
`pyproject.toml` sets ruff `fix = true`. Running `ruff check .` AUTO-EDITS
unrelated files across the repo. Always scope it (`ruff check <path>`) or pass
`--no-fix`. Task F3's agent hit this and had to revert 10 files.
