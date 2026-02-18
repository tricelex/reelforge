# apps/pipeline/signals.py
"""Post-transition signals wire FSM state changes directly to Celery task dispatch.
This is the single place where "stage changed" → "task triggered" lives.
No more scattered .delay() calls across the codebase.
"""

from django.dispatch import receiver
from django_fsm.signals import post_transition

from ***REMOVED***.pipeline.choices import EventType
from ***REMOVED***.pipeline.choices import PipelineStatus
from ***REMOVED***.pipeline.models import PipelineRun


@receiver(post_transition, sender=PipelineRun)
def pipeline_run_post_transition(sender, instance, name, source, target, **kwargs):
    """Fires after every valid FSM transition on PipelineRun.
    Maps target state → Celery task to dispatch.
    Also logs every transition to PipelineEvent automatically.
    """

    # 1. Always log the transition
    from ***REMOVED***.pipeline.models import PipelineEvent

    PipelineEvent.objects.create(
        pipeline_run=instance,
        event_type=EventType.INFO,
        event_name="FSM_TRANSITION",
        message=f"Transition: {source} → {target} (via {name})",
        metadata={"source": source, "target": target, "transition_name": name},
    )

    # 2. Dispatch appropriate Celery task based on new state
    _dispatch_task_for_state(instance, target)


def _dispatch_task_for_state(run: PipelineRun, state: str) -> None:
    """Dispatch the correct Celery task for each pipeline state."""
    from ***REMOVED***.pipeline.tasks import render_video
    from ***REMOVED***.pipeline.tasks import run_asset_job
    from ***REMOVED***.pipeline.tasks import run_pipeline_orchestrator
    from ***REMOVED***.pipeline.tasks import run_research_job
    from ***REMOVED***.pipeline.tasks import run_script_job
    from ***REMOVED***.pipeline.tasks import upload_video

    dispatch_map = {
        PipelineStatus.RESEARCHING: lambda: run_research_job.delay(str(run.channel.id), str(run.research_job.id))
        if run.research_job
        else run_pipeline_orchestrator.delay(str(run.channel.id), str(run.id)),
        PipelineStatus.SCRIPTING: lambda: run_script_job.delay(str(run.topic.id), str(run.id))
        if run.topic
        else None,
        PipelineStatus.GENERATING_ASSETS: lambda: run_asset_job.delay(str(run.script_job.id), str(run.id))
        if run.script_job
        else None,
        PipelineStatus.RENDERING: lambda: render_video.delay(str(run.production_job.id))
        if run.production_job
        else None,
        PipelineStatus.UPLOADING: lambda: upload_video.delay(str(run.distribution_job.id))
        if run.distribution_job
        else None,
        # AWAITING_APPROVAL: no task — waits for human action or auto-approve timer
        # QA: triggered directly by render_video task on completion
        # PUBLISHED, FAILED, PAUSED: no automatic dispatch
    }

    task_fn = dispatch_map.get(state)
    if task_fn:
        task_fn()
