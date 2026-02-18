import logging

from agents.tracing import TracingProcessor

logger = logging.getLogger("youtube_hq.agents")


class CostTrackingProcessor(TracingProcessor):
    """Custom tracing processor — saves token/cost data to PipelineEvent."""

    def __init__(self, pipeline_run_id: str) -> None:
        self.pipeline_run_id = pipeline_run_id

    def on_trace_end(self, trace_data: dict) -> None:
        from reelforge.pipeline.models import PipelineEvent
        from reelforge.pipeline.models import PipelineRun

        try:
            run = PipelineRun.objects.get(id=self.pipeline_run_id)
            PipelineEvent.objects.create(
                run=run,
                stage="AGENT_TRACE",
                event_type="INFO",
                message=f"Agent trace completed: {trace_data.get('name', '')}",
                detail=trace_data,
                agent_name=trace_data.get("name", ""),
            )
        except Exception:
            logger.exception("Failed to save trace")
