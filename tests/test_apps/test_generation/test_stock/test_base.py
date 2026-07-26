"""Tests for the shared footage provider contract."""

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    passes_quality_floor,
)


def _candidate(**overrides: object) -> FootageCandidate:
    defaults: dict[str, object] = {
        'provider': 'pexels',
        'external_id': '1',
        'media_type': 'video',
        'download_url': 'https://example.test/v.mp4',
        'thumb_url': 'https://example.test/t.jpg',
        'source_page_url': 'https://example.test/p',
        'width': 1920,
        'height': 1080,
        'duration_s': 10.0,
        'license': 'pexels',
        'license_url': '',
        'author': 'Someone',
        'attribution_required': False,
        'title': 'A clip',
        'tags': (),
    }
    defaults.update(overrides)
    return FootageCandidate(**defaults)  # type: ignore[arg-type]


def test_candidate_is_immutable() -> None:
    """Candidates are frozen value objects."""
    import attrs
    import pytest

    candidate = _candidate()
    with pytest.raises(attrs.exceptions.FrozenInstanceError):
        candidate.width = 640  # type: ignore[misc]


def test_quality_floor_accepts_a_good_candidate() -> None:
    """A large, long-enough, permissively licensed clip passes."""
    assert passes_quality_floor(
        _candidate(),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_rejects_low_resolution() -> None:
    """Below the width floor is rejected."""
    assert not passes_quality_floor(
        _candidate(width=640),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_rejects_short_video() -> None:
    """A video shorter than the duration floor is rejected."""
    assert not passes_quality_floor(
        _candidate(duration_s=1.0),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_rejects_video_without_duration() -> None:
    """Video with unknown duration cannot satisfy the minimum duration."""
    assert not passes_quality_floor(
        _candidate(duration_s=None),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_ignores_duration_for_images() -> None:
    """Stills have no duration and must not be rejected for it."""
    assert passes_quality_floor(
        _candidate(media_type='image', duration_s=None),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_empty_allowlist_permits_any_license() -> None:
    """An empty allowlist means 'no licence restriction'."""
    assert passes_quality_floor(
        _candidate(license='CC-BY-SA-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_license_allowlist_is_enforced_when_set() -> None:
    """A non-empty allowlist rejects licences outside it."""
    assert not passes_quality_floor(
        _candidate(license='CC-BY-SA-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['pexels', 'public-domain'],
    )


def test_unknown_license_is_always_rejected_case_insensitively() -> None:
    """Unknown licensing cannot satisfy the commercial-use floor."""
    assert not passes_quality_floor(
        _candidate(license='UnKnOwN'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['UnKnOwN'],
    )


def test_empty_license_is_always_rejected() -> None:
    """Missing licensing cannot satisfy the commercial-use floor."""
    assert not passes_quality_floor(
        _candidate(license=''),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_noncommercial_is_always_rejected() -> None:
    """NC content cannot be used on a monetized channel, allowlist or not."""
    assert not passes_quality_floor(
        _candidate(license='by-nc-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['by-nc-4.0'],
    )


def test_noderivatives_is_always_rejected() -> None:
    """ND content cannot be edited into a video, allowlist or not."""
    assert not passes_quality_floor(
        _candidate(license='by-nc-nd-2.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['by-nc-nd-2.0'],
    )


def test_share_alike_is_permitted() -> None:
    """SA is compatible with this use; only NC and ND are excluded."""
    assert passes_quality_floor(
        _candidate(license='by-sa-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )
