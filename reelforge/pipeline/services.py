from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed

if TYPE_CHECKING:
    from reelforge.pipeline.models import PipelineRun

logger = logging.getLogger("reelforge.pipeline.services")


class PipelineService:
    def __init__(self, channel) -> None:
        self.channel = channel

    def trigger_daily_batch(self) -> None:
        """Run daily batch for the channel.

        Creates new PipelineRuns in INITIALIZING state for approved topics that
        have no script yet. The operator starts each run manually from the admin.
        Also replenishes the topic pool if running low.
        """
        from reelforge.pipeline.models import PipelineRun
        from reelforge.pipeline.tasks import run_research_job_for_channel
        from reelforge.research.models import TopicIdea

        available_topics = self.channel.topic_ideas.filter(approved=True, status="PENDING").count()

        if available_topics < 3:
            run_research_job_for_channel.delay(str(self.channel.id))

        ready_topics = TopicIdea.objects.filter(
            channel=self.channel,
            approved=True,
            script_job__isnull=True,
        )[:1]

        for topic in ready_topics:
            PipelineRun.objects.create(channel=self.channel, topic=topic)
            # Run remains in INITIALIZING — operator starts it manually from admin.

    @staticmethod
    def approve_script_and_advance(run: PipelineRun) -> None:
        """Human clicks Approve in admin — advance past AWAITING_APPROVAL."""
        if can_proceed(run.begin_assets):
            run.begin_assets()
            run.save()
        else:
            msg = f"Cannot advance from {run.overall_status} to GENERATING_ASSETS"
            raise TransitionNotAllowed(msg)
