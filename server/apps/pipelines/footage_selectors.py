"""Read-only selectors for footage credits."""

import uuid

from server.apps.pipelines.logic.value_objects import (
    FootageCreditPayload,
    RunCreditsPayload,
)

_DESCRIPTION_BUDGET_CHARS = 5000


def _entry_text(credit: 'FootageCreditPayload') -> str:
    """Render one credit line as it appears in the description."""
    author = f' by {credit.author}' if credit.author else ''
    return f'{credit.title}{author} ({credit.license}) — {credit.source_url}'


def get_run_credits(run_id: str) -> RunCreditsPayload:
    """Build the attribution block, required credits first.

    Entries are truncated to the YouTube description budget. Credits with
    ``attribution_required`` are never dropped — only optional ones are.
    """
    from server.apps.assets.models import FootageCredit  # noqa: PLC0415

    rows = list(
        FootageCredit.objects.filter(run_id=uuid.UUID(run_id)).order_by(
            '-attribution_required', 'provider', 'scene_idx',
        ),
    )

    seen: dict[tuple[str, str], FootageCreditPayload] = {}
    for row in rows:
        key = (row.provider, row.source_url)
        if key in seen:
            seen[key].scene_idxs.append(row.scene_idx)
            continue
        seen[key] = FootageCreditPayload(
            provider=row.provider,
            license=row.license,
            license_url=row.license_url,
            author=row.author,
            source_url=row.source_url,
            title=row.title,
            attribution_required=row.attribution_required,
            scene_idxs=[row.scene_idx],
        )

    entries: list[FootageCreditPayload] = []
    budget = _DESCRIPTION_BUDGET_CHARS
    truncated = False
    for entry in seen.values():
        cost = len(_entry_text(entry)) + 1
        if cost > budget and not entry.attribution_required:
            truncated = True
            continue
        budget -= cost
        entries.append(entry)
    return RunCreditsPayload(entries=entries, truncated=truncated)
