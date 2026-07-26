"""Shared contract for stock/archival footage providers."""

from collections.abc import Sequence
from typing import Literal, Protocol, final

import attrs

MediaType = Literal['video', 'image']


@final
@attrs.define(slots=True, frozen=True)
class FootageCandidate:
    """One searchable media item returned by a footage provider."""

    provider: str
    external_id: str
    media_type: MediaType
    download_url: str
    thumb_url: str
    source_page_url: str
    width: int
    height: int
    duration_s: float | None
    license: str
    license_url: str
    author: str
    attribution_required: bool
    title: str
    tags: tuple[str, ...]


class FootageProvider(Protocol):
    """A searchable source of stock or public-domain media."""

    name: str

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Return candidates matching the query, best-effort ordered."""
        ...


def is_commercially_usable(license_code: str) -> bool:
    """Return False for missing, unknown, NC, or ND licences.

    These channels are monetized and every clip is edited into a longer
    work, so ``nc`` (no commercial use) and ``nd`` (no derivative works)
    material can never be used. This floor is not configurable — an empty
    ``allowed_licenses`` must not be read as permission to use NC/ND.

    >>> is_commercially_usable('by-sa-4.0')
    True
    >>> is_commercially_usable('by-nc-nd-2.0')
    False
    >>> is_commercially_usable('unknown')
    False
    """
    normalized = license_code.strip().casefold()
    if not normalized or normalized == 'unknown':
        return False
    parts = set(normalized.replace('_', '-').split('-'))
    return not ({'nc', 'nd'} & parts)


def passes_quality_floor(
    candidate: FootageCandidate,
    *,
    min_width: int,
    min_duration_s: float,
    allowed_licenses: Sequence[str],
) -> bool:
    """Return True when a candidate clears the channel's quality floor.

    An empty ``allowed_licenses`` means no *additional* restriction beyond
    the always-on NC/ND exclusion. Duration is only checked for video —
    stills legitimately have ``duration_s=None``.
    """
    if not is_commercially_usable(candidate.license):
        return False
    if candidate.width < min_width:
        return False
    if candidate.media_type == 'video':
        if candidate.duration_s is None:
            return False
        if candidate.duration_s < min_duration_s:
            return False
    return not allowed_licenses or candidate.license in allowed_licenses
