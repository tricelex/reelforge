from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from agents import Agent
from agents import Runner
from agents import Tool
from agents import handoff
from agents import trace
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

if TYPE_CHECKING:
    from reelforge.channels.models import Channel
    from reelforge.pipeline.models import PipelineRun

logger = logging.getLogger("youtube_hq.orchestrator")


def build_orchestrator(channel: Channel, pipeline_run: PipelineRun) -> Agent:
    """The OrchestratorAgent is the brain of the entire pipeline.
    It:
    - Understands the full pipeline state
    - Decides which stage to execute next
    - Hands off to specialized sub-agents
    - Handles errors and retry decisions
    - Communicates status back to the pipeline
    """

    # Build sub-agents
    from reelforge.agents.asset_agent import build_asset_agent
    from reelforge.agents.qa_agent import build_qa_agent
    from reelforge.agents.research_agent import build_research_agent
    from reelforge.agents.script_agent import build_script_agent

    # Handoff tools (these transfer control to sub-agents)
    research_agent = build_research_agent(channel)
    script_agent = build_script_agent(channel, pipeline_run.topic)
    asset_agent = build_asset_agent(channel, pipeline_run.script_job)
    qa_agent = build_qa_agent()

    # Status reporting tools
    @Tool(name="get_pipeline_status", description="Get the current state of the pipeline run.")
    def get_pipeline_status(pipeline_run_id: str) -> dict[str, Any]:
        from reelforge.pipeline.models import PipelineRun

        run = PipelineRun.objects.prefetch_related("events").get(id=pipeline_run_id)
        return {
            "current_stage": run.current_stage,
            "overall_status": run.overall_status,
            "topic": run.topic.title_idea if run.topic else None,
            "script_status": run.script_job.status if run.script_job else None,
            "asset_status": run.asset_job.status if run.asset_job else None,
            "production_status": run.production_job.status if run.production_job else None,
            "last_error": run.events.filter(event_type="ERROR").last().message
            if run.events.filter(event_type="ERROR").exists()
            else None,
        }

    @Tool(name="log_pipeline_event", description="Log an event to the pipeline audit trail.")
    def log_pipeline_event(
        pipeline_run_id: str, stage: str, event_type: str, message: str, detail: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from reelforge.pipeline.models import PipelineEvent
        from reelforge.pipeline.models import PipelineRun

        run = PipelineRun.objects.get(id=pipeline_run_id)
        event = PipelineEvent.objects.create(
            run=run,
            stage=stage,
            event_type=event_type,
            message=message,
            detail=detail or {},
            agent_name="OrchestratorAgent",
        )
        return {"logged": True, "event_id": str(event.id)}

    @Tool(name="advance_pipeline_stage", description="Advance the pipeline run to a new stage.")
    def advance_pipeline_stage(pipeline_run_id: str, new_stage: str) -> dict[str, Any]:
        from django_fsm import TransitionNotAllowed

        from reelforge.pipeline.models import PipelineRun

        run = PipelineRun.objects.get(id=pipeline_run_id)
        try:
            run.advance_to(new_stage)
            return {"success": True, "new_stage": new_stage, "available_next": run.available_transitions}
        except TransitionNotAllowed as e:
            return {
                "success": False,
                "error": str(e),
                "current_stage": run.overall_status,
                "valid_transitions": run.available_transitions,
            }

    @Tool(name="pause_pipeline_for_review", description="Pause pipeline and request operator review.")
    def pause_pipeline_for_review(pipeline_run_id: str, reason: str, stage: str) -> dict[str, Any]:
        from reelforge.pipeline.models import PipelineRun

        run = PipelineRun.objects.get(id=pipeline_run_id)
        run.overall_status = "PAUSED"
        run.current_stage = stage
        run.save()
        # Trigger notification
        from reelforge.services.notifications import send_review_request

        send_review_request(run=run, reason=reason)
        return {"paused": True, "reason": reason}

    @Tool(name="trigger_celery_task", description="Trigger a specific Celery task for heavy processing.")
    def trigger_celery_task(task_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Celery handles CPU/GPU intensive work; agent handles logic/decisions."""
        from celery import current_app

        result = current_app.send_task(task_name, kwargs=kwargs)
        return {"task_id": result.id, "task_name": task_name}

    @Tool(name="evaluate_stage_output", description="Evaluate the quality of a pipeline stage output.")
    def evaluate_stage_output(
        stage: str, output_data: dict[str, Any], channel_config: dict[str, Any]
    ) -> dict[str, Any]:
        from reelforge.services.providers.registry import get_llm_provider

        llm = get_llm_provider()
        prompt = f"""Evaluate this {stage} output for quality:
        Output: {output_data}
        Channel requirements: {channel_config}

        Is this acceptable to proceed? Be strict.
        Return JSON: {{
            "acceptable": bool,
            "score": float (0-10),
            "issues": [str],
            "recommendation": "PROCEED|RETRY|ESCALATE"
        }}"""
        return llm.complete_json(prompt)

    return Agent(
        name="OrchestratorAgent",
        model="gpt-4o",
        instructions=f"""
        {RECOMMENDED_PROMPT_PREFIX}

        You are the master orchestrator for a YouTube automation pipeline.
        Pipeline Run ID: {pipeline_run.id}
        Channel: {channel.name} | Niche: {channel.target_niches}

        YOUR ROLE:
        You make ALL decisions about pipeline flow. You do NOT do the work yourself —
        you delegate to specialized sub-agents via handoffs and Celery tasks for
        heavy processing. You evaluate outputs and decide whether to proceed, retry,
        or escalate to human review.

        PIPELINE STAGES (in order):
        1. RESEARCHING     → Hand off to ResearchAgent
        2. SCRIPTING       → Hand off to ScriptAgent
        3. AWAITING_APPROVAL → Pause for human review (unless auto_approve=True)
        4. GENERATING_ASSETS → Hand off to AssetAgent
        5. RENDERING       → Trigger Celery render task
        6. QA              → Hand off to QAAgent
        7. UPLOADING       → Trigger Celery upload task
        8. PUBLISHED       → Done

        DECISION FRAMEWORK:
        - After each stage: evaluate_stage_output before advancing
        - If score < 6: retry the stage (max {channel.auto_approve_delay_hrs}h for auto-approve)
        - If score 6-7: log warning, advance with note
        - If score >= 8: advance immediately
        - If retry_count >= max_retries: pause_pipeline_for_review

        ALWAYS:
        - log_pipeline_event at start and end of each stage
        - advance_pipeline_stage when moving forward
        - Include cost tracking in all event logs

        NEVER:
        - Skip QA stage
        - Auto-upload without QA pass
        - Proceed if critical error unresolved
        """,
        tools=[
            get_pipeline_status,
            log_pipeline_event,
            advance_pipeline_stage,
            pause_pipeline_for_review,
            trigger_celery_task,
            evaluate_stage_output,
        ],
        handoffs=[
            handoff(research_agent, tool_name_override="delegate_to_research_agent"),
            handoff(script_agent, tool_name_override="delegate_to_script_agent"),
            handoff(asset_agent, tool_name_override="delegate_to_asset_agent"),
            handoff(qa_agent, tool_name_override="delegate_to_qa_agent"),
        ],
    )


async def run_orchestrator(channel_id: str, pipeline_run_id: str) -> Any:
    """Entry point called by Celery to start the orchestrator."""
    from reelforge.channels.models import Channel
    from reelforge.pipeline.models import PipelineRun

    channel = await Channel.objects.aget(id=channel_id)
    pipeline_run = await PipelineRun.objects.aget(id=pipeline_run_id)

    orchestrator = build_orchestrator(channel, pipeline_run)

    with trace(f"Pipeline Run: {pipeline_run_id}"):
        return await Runner.run(
            orchestrator,
            input=f"""
            Start pipeline run {pipeline_run_id} for channel '{channel.name}'.
            Current stage: {pipeline_run.current_stage or "NOT_STARTED"}.
            Topic: {pipeline_run.topic.title_idea if pipeline_run.topic else "Not yet selected"}.

            Get pipeline status, then proceed with the appropriate next stage.
            """,
            max_turns=50,  # Safety limit on autonomous turns
        )
