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
