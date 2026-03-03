# apps/pipeline/signals.py
"""Post-transition signals log FSM state changes to the PipelineEvent audit trail.
Task dispatch is handled explicitly by admin actions — not by this signal.
"""

from django.dispatch import receiver
from django_fsm.signals import post_transition

from ***REMOVED***.pipeline.choices import EventType
from ***REMOVED***.pipeline.models import PipelineRun


@receiver(post_transition, sender=PipelineRun)
def pipeline_run_post_transition(sender, instance, name, source, target, **kwargs) -> None:
    """Fires after every valid FSM transition on PipelineRun.
    Logs every transition to PipelineEvent automatically.
    Task dispatch is handled explicitly by the admin action that triggered the transition.
    """
    from ***REMOVED***.pipeline.models import PipelineEvent

    PipelineEvent.objects.create(
        pipeline_run=instance,
        event_type=EventType.INFO,
        event_name="FSM_TRANSITION",
        message=f"Transition: {source} → {target} (via {name})",
        metadata={"source": source, "target": target, "transition_name": name},
    )
