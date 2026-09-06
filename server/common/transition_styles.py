"""Canonical vocabulary for assembly chapter transition style names.

Shared between server.apps.channels (where a channel's transition_styles
pool is configured) and server.apps.rendering (where those names are
mapped to an FFmpeg xfade transition) so the two can never drift apart -
a channel previously could be configured with a style name rendering
didn't recognize, silently degrading every transition to a plain
cross-dissolve with no error anywhere.
"""

HARD_CUT = 'hard_cut'

XFADE_TRANSITION_STYLES: frozenset[str] = frozenset({
    'cross_dissolve',
    'long_dissolve',
    'fade',
    'fade_black',
    'fade_to_black',
    'fade_white',
    'slide_left',
    'slide_right',
    'slide_up',
    'slide_down',
    'slow_pan',
    'slow_push_cut',
    'wipe_left',
    'wipe_right',
    'zoom_in',
})

VALID_TRANSITION_STYLES: frozenset[str] = XFADE_TRANSITION_STYLES | {HARD_CUT}
