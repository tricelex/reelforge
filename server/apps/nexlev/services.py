"""NexLev read/write service — populated in later tasks."""

from typing import final

import attrs


@final
@attrs.define(slots=True, frozen=True)
class NexLevService:
    """Records-first NexLev reads: refetch only stale sections."""
