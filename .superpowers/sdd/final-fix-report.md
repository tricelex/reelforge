# Final documentary-foundations fixes

## Status

All four Important whole-branch review findings are fixed:

- Redis stock-search keys now include `min_width`.
- Empty and case-insensitive `unknown` licences fail the quality floor.
- Archive.org selects the highest declared-resolution MP4 and parses scalar,
  `H:MM:SS`, and `M:SS` durations defensively.
- `FootageCredit` and `FootageSourcingConfig` are registered in Django admin;
  footage credits are read-only provenance records.

## TDD evidence

Regression tests were added before implementation. The initial focused run
failed on all new behaviors: 8 failed, 38 passed, with one transient test
database setup timeout. After implementation and lint-driven simplification,
the complete focused suite passed.

## Verification

```text
docker compose exec web pytest \
  tests/test_apps/test_generation/test_stock/ \
  tests/test_apps/test_assets/test_footage_credit.py \
  tests/test_apps/test_channels/test_footage_sourcing_config.py \
  tests/test_server/test_admin.py -v --no-cov
Result: 151 passed in 11.91s

docker compose exec web ruff check --no-fix <11 touched Python paths>
Result: All checks passed

docker compose exec web ruff format --check <11 touched Python paths>
Result: 11 files already formatted

docker compose exec web mypy <5 touched production modules>
Result: Success: no issues found in 5 source files
```

No migrations or external API calls were required.
