"""Pure helpers for assembling editor-handoff zip packages.

Stages gather file bytes (fetching Assets, querying models) and hand a flat
``{relative_path: content}`` mapping to the functions below, which build the
README, MANIFEST, and final zip bytes without touching Django or the ORM.
"""

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

_MAX_PACKAGE_ENTRIES = 5000

README_LONGFORM = """# Editor Package — Long-form

This package contains everything needed to reassemble the video in
DaVinci Resolve. The voiceover audio is the master clock — build the
timeline against it, not against the individual scene clips.

## Import steps

1. Create a Resolve project and a new timeline.
2. Import `audio/vo/ch_NNN.mp3` files onto an audio track, in chapter
   order — they are the master clock for the whole edit.
3. Import `video/scenes` (and `stills/scenes`, if present) and place
   each clip using `timeline/markers.csv` or `timeline/markers.edl`
   for exact start/end timecodes.
4. Import `audio/music/bed.*` onto a separate audio track at the gain
   noted in `audio/music/music_notes.json`.
5. Import `captions/captions.srt` (or `captions.ass`) as a subtitle
   track synced to the voiceover.
6. Read `docs/EDIT_BRIEF.md` for chapter intents, scene notes, and
   music direction before making creative edits.

See `MANIFEST.json` for every packaged file's checksum and the
originating pipeline asset id.
"""

README_CLIPPING = """# Editor Package — Clipping

This package contains cut candidates, markers, and rough preview
renders for editing short clips. It intentionally omits the source
video — bring your own local copy and use it as the master clock.

## Import steps

1. Import your own local copy of the source video into Resolve and
   use it as the master timeline.
2. Import `candidates/markers.edl` onto that timeline to mark every
   approved candidate's start/end.
3. Import `candidates/candidates.csv` (or `.json`) for titles, hooks,
   and scores per candidate.
4. Import `captions/full_transcript.srt` as a subtitle track on the
   master; `captions/per_candidate/*.srt` are pre-sliced per clip for
   dropping onto individual clip timelines.
5. Use `previews/clip_NN_preview.mp4` as rough-cut reference only —
   they are re-encoded trims, not final-quality exports.

See `MANIFEST.json` for every packaged file's checksum and the
originating pipeline asset id.
"""


def sha256_hex(content: bytes) -> str:
    """Return the hex SHA-256 digest of ``content``."""
    assert isinstance(content, bytes), 'content must be bytes'  # noqa: S101
    digest = hashlib.sha256(content).hexdigest()
    assert len(digest) == 64, (  # noqa: S101
        'sha256 hex digest must be 64 chars'
    )
    return digest


def short_run_id(run_id: str) -> str:
    """Return the first 8 hex characters of a run UUID, for folder naming."""
    assert run_id, 'run_id is required'  # noqa: S101
    cleaned = run_id.replace('-', '')
    assert cleaned, 'run_id must contain hex characters'  # noqa: S101
    return cleaned[:8]


def package_root_name(run_id: str, *, is_clipping: bool) -> str:
    """Return the top-level folder/zip name for one package build."""
    assert run_id, 'run_id is required'  # noqa: S101
    suffix = 'clip' if is_clipping else 'longform'
    return f'run_{short_run_id(run_id)}_{suffix}_editor_package'


def collect_source_asset_ids(
    upstream: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Flatten every ``*asset_id`` field across upstream outputs.

    Keys are ``{stage_key}.{field}`` so MANIFEST.json can trace each
    packaged artifact back to the pipeline stage that produced it.
    """
    assert isinstance(upstream, dict), 'upstream must be a dict'  # noqa: S101
    ids: dict[str, str] = {}
    for stage_key, output in upstream.items():
        assert isinstance(output, dict), (  # noqa: S101
            f'upstream[{stage_key!r}] must be a dict'
        )
        for field, value in output.items():
            if isinstance(value, str) and field.endswith('asset_id'):
                ids[f'{stage_key}.{field}'] = value
    return ids


def build_readme(*, is_clipping: bool) -> bytes:
    """Return the README.md bytes for the given package kind."""
    text = README_CLIPPING if is_clipping else README_LONGFORM
    assert text.strip(), 'README template must not be empty'  # noqa: S101
    return text.encode()


def build_manifest(
    files: dict[str, bytes],
    *,
    source_asset_ids: dict[str, str],
    root_name: str,
) -> bytes:
    """Build MANIFEST.json bytes describing every other packaged file."""
    assert files, 'files must be non-empty to build a manifest'  # noqa: S101
    assert root_name, 'root_name is required'  # noqa: S101
    entries = [
        {
            'path': path,
            'size_bytes': len(content),
            'sha256': sha256_hex(content),
        }
        for path, content in sorted(files.items())
    ]
    manifest = {
        'root_name': root_name,
        'generated_at': datetime.now(UTC).isoformat(),
        'source_asset_ids': dict(sorted(source_asset_ids.items())),
        'file_count': len(entries),
        'files': entries,
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode()


def build_zip(files: dict[str, bytes], *, root_name: str) -> bytes:
    """Zip ``{relative_path: content}`` entries under one root folder."""
    assert files, 'files must be non-empty to build a package'  # noqa: S101
    assert root_name, 'root_name is required'  # noqa: S101
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        ordered = sorted(files.items())
        for i, (path, content) in enumerate(ordered):
            assert i < _MAX_PACKAGE_ENTRIES, (  # noqa: S101
                'entry count exceeded bound'
            )
            zf.writestr(f'{root_name}/{path}', content)
    result = buf.getvalue()
    assert result, 'zip output must not be empty'  # noqa: S101
    return result
