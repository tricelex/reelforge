from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed

if TYPE_CHECKING:
    from reelforge.pipeline.models import PipelineRun

logger = logging.getLogger("reelforge.pipeline.services")


class PipelineService:
    def __init__(self, channel):
        self.channel = channel

    def trigger_daily_batch(self):
        from reelforge.pipeline.models import PipelineRun
        from reelforge.research.models import TopicIdea

        available_topics = self.channel.topics.filter(status="COMPLETED", script_job__isnull=True).count()

        if available_topics < 3:
            from reelforge.research.tasks import run_research_job_for_channel

            run_research_job_for_channel.delay(str(self.channel.id))

        ready_topics = TopicIdea.objects.filter(channel=self.channel, status="COMPLETED", script_job__isnull=True)[:1]

        for topic in ready_topics:
            run = PipelineRun.objects.create(channel=self.channel, topic=topic)
            run.begin_research()  # FSM: INITIALIZING → RESEARCHING
            run.save()
            # post_transition signal fires → run_research_job.delay() called automatically

    @staticmethod
    def retry_current_stage(run: PipelineRun) -> bool:
        """Determine correct retry transition based on current state.
        FSM conditions=[can_retry] prevent retry if max_retries exceeded.
        """
        retry_map = {
            PipelineRun.FAILED: {
                "SCRIPTING": run.retry_scripting,
                "GENERATING_ASSETS": run.retry_assets,
                "RENDERING": run.retry_rendering,
                "UPLOADING": run.retry_upload,
            }
        }

        if run.overall_status == PipelineRun.FAILED:
            # Determine which stage failed by checking stage objects
            stage = _identify_failed_stage(run)
            fn = retry_map[PipelineRun.FAILED].get(stage)
            if fn and can_proceed(fn):
                fn()
                run.save()  # post_transition → Celery dispatch
                return True
        return False

    @staticmethod
    def approve_script_and_advance(run: PipelineRun):
        """Human clicks Approve in admin — advance past AWAITING_APPROVAL."""
        if can_proceed(run.begin_assets):
            run.begin_assets()
            run.save()
        else:
            raise TransitionNotAllowed(f"Cannot advance from {run.overall_status} to GENERATING_ASSETS")
