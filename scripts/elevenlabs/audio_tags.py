"""Strip ElevenLabs v3 [bracket] audio/emotion tags from narration text.

Standalone copy of server/apps/pipelines/logic/audio_tags.py — this
module intentionally has zero Django dependency so scripts/elevenlabs/
can run without bootstrapping the Django app.
"""

import re

_TAG_RE = re.compile(r'\[[^\]\n]{1,60}\]')
_WS_RE = re.compile(r'[ \t]{2,}')


def strip_audio_tags(text: str) -> str:
    """Remove [bracket] audio/emotion tags, collapsing extra whitespace."""
    without_tags = _TAG_RE.sub('', text)
    lines = [
        _WS_RE.sub(' ', line).strip() for line in without_tags.splitlines()
    ]
    return '\n'.join(line for line in lines if line)
