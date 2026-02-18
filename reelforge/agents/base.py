import logging

from agents.tracing import TracingProcessor

logger = logging.getLogger("***REMOVED***.agents")


class CostTrackingProcessor(TracingProcessor):
    """Custom tracing processor — saves token/cost data to PipelineEvent."""

    def __init__(self, pipeline_run_id: str) -> None:
        self.pipeline_run_id = pipeline_run_id

    def on_trace_end(self, trace_data: dict) -> None:
        from ***REMOVED***.pipeline.models import PipelineEvent
        from ***REMOVED***.pipeline.models import PipelineRun

        try:
            run = PipelineRun.objects.get(id=self.pipeline_run_id)
            PipelineEvent.objects.create(
                pipeline_run=run,
                event_type="INFO",
                event_name="AGENT_TRACE",
                message=f"Agent trace completed: {trace_data.get('name', '')}",
                metadata=trace_data,
                triggered_by_agent=trace_data.get("name", ""),
            )
        except Exception:
            logger.exception("Failed to save trace")
