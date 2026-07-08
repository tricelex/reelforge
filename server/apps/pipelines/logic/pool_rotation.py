"""Shared "rotate through a per-channel style pool" helper.

Used wherever a stage picks one value from a small per-channel config pool
(camera movement, transition style, ...) deterministically by index, falling
back to a default when the pool is empty. This is intentionally a pure
index-cycle, not a repeat-avoiding picker — see outline.py's `_pick_format`
for the heavier DB-backed "avoid recent repeats" variant used for
StoryFormat rotation, which is a different concern (avoiding repeats across
runs over time, not just varying within one run).
"""


def pick_cyclic(pool: list[str], idx: int, default: str) -> str:
    """Return pool[idx % len(pool)], or `default` when pool is empty."""
    if not pool:
        return default
    return pool[idx % len(pool)]
