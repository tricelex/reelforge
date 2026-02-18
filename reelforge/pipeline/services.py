from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed

from ***REMOVED***.pipeline.choices import PipelineStatus

if TYPE_CHECKING:
    from ***REMOVED***.pipeline.models import PipelineRun

logger = logging.getLogger("***REMOVED***.pipeline.services")


class PipelineService:
    def __init__(self, channel):
        self.channel = channel

    def trigger_daily_batch(self):
        from ***REMOVED***.pipeline.models import PipelineRun
        from ***REMOVED***.pipeline.tasks import run_research_job_for_channel
        from ***REMOVED***.research.models import TopicIdea

        available_topics = self.channel.topic_ideas.filter(approved=True, status="PENDING").count()

        if available_topics < 3:
            run_research_job_for_channel.delay(str(self.channel.id))

        ready_topics = TopicIdea.objects.filter(
            channel=self.channel,
            approved=True,
            script_job__isnull=True,
        )[:1]

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
            PipelineStatus.SCRIPTING: run.retry_scripting,
            PipelineStatus.GENERATING_ASSETS: run.retry_assets,
            PipelineStatus.RENDERING: run.retry_rendering,
            PipelineStatus.UPLOADING: run.retry_upload,
        }

        if run.overall_status == PipelineStatus.FAILED:
            # Determine which stage failed by checking stage objects
            stage = _identify_failed_stage(run)
            fn = retry_map.get(stage)
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


def _identify_failed_stage(run: PipelineRun) -> str:
    """Determine which stage caused the pipeline failure by checking stage job statuses."""
    from ***REMOVED***.core.models import PipelineStatusChoices

    if run.distribution_job and run.distribution_job.status == PipelineStatusChoices.FAILED:
        return PipelineStatus.UPLOADING
    if run.production_job and run.production_job.status == PipelineStatusChoices.FAILED:
        return PipelineStatus.RENDERING
    if run.asset_job and run.asset_job.status == PipelineStatusChoices.FAILED:
        return PipelineStatus.GENERATING_ASSETS
    if run.script_job and run.script_job.status == PipelineStatusChoices.FAILED:
        return PipelineStatus.SCRIPTING
    return run.current_stage or "UNKNOWN"
