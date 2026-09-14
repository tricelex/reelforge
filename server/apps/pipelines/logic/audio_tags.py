"""Strip ElevenLabs v3 [bracket] audio/emotion tags from narration text."""

import re

_TAG_RE = re.compile(r'\[[^\]\n]{1,60}\]')
_WS_RE = re.compile(r'[ \t]{2,}')


def strip_audio_tags(text: str) -> str:
    """Remove [bracket] audio/emotion tags, collapsing extra whitespace.

    ElevenLabs v3 audio tags (e.g. ``[sighs]``, ``[whispers]``) are never
    spoken aloud, so a transcript submitted for forced alignment must not
    contain them — the aligner would try to match a word that isn't in
    the audio.
    """
    without_tags = _TAG_RE.sub('', text)
    lines = [
        _WS_RE.sub(' ', line).strip() for line in without_tags.splitlines()
    ]
    return '\n'.join(line for line in lines if line)
