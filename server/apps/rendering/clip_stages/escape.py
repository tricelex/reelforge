r"""FFmpeg filtergraph escaping helpers for drawtext-based stages.

Values interpolated into a filtergraph inside single quotes need two levels
of care:

1. Graph level: inside ``'...'`` nothing is special *except* the closing
   quote itself. An embedded ``'`` must be spliced as ``'\''`` (close quote,
   escaped literal quote, reopen quote) — the previously used ``\'`` form
   terminates the quoted section and lets commas/colons in the remaining
   text split the filtergraph (symptom: ``No such filter: '0'``).
2. drawtext text expansion: ``\`` and ``%`` are special in the ``text``
   option value and must be backslash-escaped.
"""


def drawtext_escape(value: str) -> str:
    """Escape a drawtext ``text`` value for use inside single quotes."""
    escaped = value.replace('\\', '\\\\').replace('%', '\\%')
    return escaped.replace("'", "'\\''")


def filter_path_escape(value: str) -> str:
    """Escape a file path for use inside single quotes in a filtergraph."""
    return value.replace("'", "'\\''")
