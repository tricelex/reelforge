from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField
from django_fsm import transition

from reelforge.core.models import BaseAbstractModel
from reelforge.pipeline.choices import EventType
from reelforge.pipeline.choices import PipelineStatus


class PipelineRun(BaseAbstractModel):
    """Orchestrates a complete video production cycle.
    Links to all stage jobs via foreign keys.
    Uses FSM for overall pipeline state management.
    """

    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="pipeline_runs",
    )

    # Overall status (FSM-managed)
    overall_status = FSMField(
        default=PipelineStatus.INITIALIZING,
        choices=PipelineStatus.choices,
        protected=True,
        db_index=True,
    )

    # Stage job links (nullable until created)
    research_job = models.ForeignKey(
        "research.ResearchJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )
    topic = models.ForeignKey(
        "research.TopicIdea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )
    script_job = models.ForeignKey(
        "scripts.ScriptJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )
    asset_job = models.ForeignKey(
        "assets.AssetJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )
    production_job = models.ForeignKey(
        "production.ProductionJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )
    distribution_job = models.ForeignKey(
        "distribution.DistributionJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_runs",
    )

    # Timeline
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the pipeline actually started processing"),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the pipeline finished (PUBLISHED state)"),
    )
    failed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the pipeline failed (FAILED state)"),
    )

    # Orchestrator context
    orchestrator_run_id = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("OpenAI Agents SDK run ID"),
    )
    orchestrator_turns = models.PositiveIntegerField(
        default=0,
        help_text=_("Number of agent turns in this run"),
    )
    current_stage = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Current stage name for display/logging purposes"),
    )
    last_agent_decision = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Last decision made by OrchestratorAgent"),
    )

    # Cost tracking - aggregated from all stages
    total_agent_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text=_("Sum of all AI agent costs (LLM calls)"),
    )
    total_asset_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text=_("Sum of all asset generation costs (TTS, images, thumbnails)"),
    )

    # Final video info (denormalized for fast display)
    final_video_title = models.CharField(max_length=255, blank=True)
    final_video_url = models.URLField(blank=True)
    final_video_duration_seconds = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Pipeline Run")
        verbose_name_plural = _("Pipeline Runs")
        indexes = [
            models.Index(fields=["overall_status", "created_at"]),
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["orchestrator_run_id"]),
        ]

    def __str__(self) -> str:
        title = self.final_video_title or f"Run {str(self.id)[:8]}"
        return f"Pipeline: {title[:60]}"

    # ── FSM Transitions ────────────────────────────────────────────

    @transition(
        field=overall_status,
        source=PipelineStatus.INITIALIZING,
        target=PipelineStatus.RESEARCHING,
    )
    def begin_research(self) -> None:
        """Start research phase."""
        self.current_stage = PipelineStatus.RESEARCHING
        if not self.started_at:
            self.started_at = timezone.now()

    @transition(
        field=overall_status,
        source=PipelineStatus.RESEARCHING,
        target=PipelineStatus.SCRIPTING,
    )
    def begin_scripting(self) -> None:
        """Research complete, start script generation."""
        self.current_stage = PipelineStatus.SCRIPTING

    @transition(
        field=overall_status,
        source=PipelineStatus.SCRIPTING,
        target=PipelineStatus.AWAITING_APPROVAL,
    )
    def await_approval(self) -> None:
        """Script ready for review."""
        self.current_stage = PipelineStatus.AWAITING_APPROVAL

    @transition(
        field=overall_status,
        source=PipelineStatus.AWAITING_APPROVAL,
        target=PipelineStatus.GENERATING_ASSETS,
    )
    def begin_assets(self) -> None:
        """Approval received, start asset generation.
        Can also come from SCRIPTING (auto-approve).
        """
        self.current_stage = PipelineStatus.GENERATING_ASSETS

    @transition(
        field=overall_status,
        source=PipelineStatus.GENERATING_ASSETS,
        target=PipelineStatus.RENDERING,
    )
    def begin_rendering(self) -> None:
        """Assets ready, start video render."""
        self.current_stage = PipelineStatus.RENDERING

    @transition(
        field=overall_status,
        source=PipelineStatus.RENDERING,
        target=PipelineStatus.QA,
    )
    def begin_qa(self) -> None:
        """Render complete, run QA checks."""
        self.current_stage = PipelineStatus.QA

    @transition(
        field=overall_status,
        source=PipelineStatus.QA,
        target=PipelineStatus.UPLOADING,
    )
    def begin_upload(self) -> None:
        """QA passed, start upload."""
        self.current_stage = PipelineStatus.UPLOADING

    @transition(
        field=overall_status,
        source=PipelineStatus.UPLOADING,
        target=PipelineStatus.PUBLISHED,
    )
    def mark_published(self) -> None:
        """Upload complete, video is live."""
        self.current_stage = PipelineStatus.PUBLISHED
        if not self.completed_at:
            self.completed_at = timezone.now()

    @transition(
        field=overall_status,
        source="*",
        target=PipelineStatus.FAILED,
    )
    def mark_failed(self, reason: str = "") -> None:
        """Pipeline failed at any stage."""
        self.current_stage = PipelineStatus.FAILED
        if not self.failed_at:
            self.failed_at = timezone.now()
        if reason:
            self.last_agent_decision = {"action": "failed", "reason": reason}

    @transition(
        field=overall_status,
        source="*",
        target=PipelineStatus.PAUSED,
    )
    def pause_pipeline(self, reason: str = "") -> None:
        """Pause for manual intervention."""
        self.current_stage = PipelineStatus.PAUSED
        if reason:
            self.last_agent_decision = {"action": "pause", "reason": reason}

    # Resume transitions (from PAUSED back to correct stage)
    @transition(
        field=overall_status,
        source=PipelineStatus.PAUSED,
        target=PipelineStatus.GENERATING_ASSETS,
    )
    def resume_to_assets(self) -> None:
        """Resume from pause to asset generation."""
        self.current_stage = PipelineStatus.GENERATING_ASSETS

    @transition(
        field=overall_status,
        source=PipelineStatus.PAUSED,
        target=PipelineStatus.RENDERING,
    )
    def resume_to_rendering(self) -> None:
        """Resume from pause to rendering."""
        self.current_stage = PipelineStatus.RENDERING

    @transition(
        field=overall_status,
        source=PipelineStatus.PAUSED,
        target=PipelineStatus.UPLOADING,
    )
    def resume_to_upload(self) -> None:
        """Resume from pause to upload."""
        self.current_stage = PipelineStatus.UPLOADING

    # Retry transitions (from FAILED back to re-runnable stages)
    @transition(
        field=overall_status,
        source=PipelineStatus.FAILED,
        target=PipelineStatus.SCRIPTING,
    )
    def retry_scripting(self) -> None:
        """Retry from scripting stage."""
        self.current_stage = PipelineStatus.SCRIPTING
        self.failed_at = None

    @transition(
        field=overall_status,
        source=PipelineStatus.FAILED,
        target=PipelineStatus.GENERATING_ASSETS,
    )
    def retry_assets(self) -> None:
        """Retry asset generation."""
        self.current_stage = PipelineStatus.GENERATING_ASSETS
        self.failed_at = None

    @transition(
        field=overall_status,
        source=PipelineStatus.FAILED,
        target=PipelineStatus.RENDERING,
    )
    def retry_rendering(self) -> None:
        """Retry video rendering."""
        self.current_stage = PipelineStatus.RENDERING
        self.failed_at = None

    @transition(
        field=overall_status,
        source=PipelineStatus.FAILED,
        target=PipelineStatus.UPLOADING,
    )
    def retry_upload(self) -> None:
        """Retry YouTube upload."""
        self.current_stage = PipelineStatus.UPLOADING
        self.failed_at = None

    # ── Properties ─────────────────────────────────────────────────

    @property
    def available_transitions(self) -> list[str]:
        """Returns valid FSM transitions from current state."""
        from django_fsm import get_available_FIELD_transitions

        return [t.name for t in get_available_FIELD_transitions(self, self.overall_status)]

    @property
    def duration_hours(self) -> float:
        """Total pipeline duration in hours."""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() / 3600
        if self.failed_at and self.started_at:
            delta = self.failed_at - self.started_at
            return delta.total_seconds() / 3600
        if self.started_at:
            # In progress — show time since start
            delta = timezone.now() - self.started_at
            return delta.total_seconds() / 3600
        return 0.0

    @property
    def total_cost_usd(self) -> float:
        return float(self.total_agent_cost_usd + self.total_asset_cost_usd)

    def advance_to(self, stage: str) -> None:
        """Helper method for OrchestratorAgent to advance pipeline stage.
        Maps stage name to the correct FSM transition method.
        Raises TransitionNotAllowed if the move is illegal.
        """
        from django_fsm import TransitionNotAllowed
        from django_fsm import can_proceed

        transition_map = {
            PipelineStatus.RESEARCHING: self.begin_research,
            PipelineStatus.SCRIPTING: self.begin_scripting,
            PipelineStatus.AWAITING_APPROVAL: self.await_approval,
            PipelineStatus.GENERATING_ASSETS: self.begin_assets,
            PipelineStatus.RENDERING: self.begin_rendering,
            PipelineStatus.QA: self.begin_qa,
            PipelineStatus.UPLOADING: self.begin_upload,
            PipelineStatus.PUBLISHED: self.mark_published,
        }
        fn = transition_map.get(stage)
        if not fn:
            msg = f"Unknown stage: {stage}"
            raise ValueError(msg)
        if not can_proceed(fn):
            msg = f"Cannot transition from {self.overall_status} to {stage}"
            raise TransitionNotAllowed(msg)
        fn()
        self.save(update_fields=["overall_status", "updated_at"])


class PipelineEvent(BaseAbstractModel):
    """Immutable audit log of all pipeline run events.
    Records state changes, agent decisions, errors, operator actions.
    NEVER update or delete — append-only.
    """

    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="events",
    )

    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices,
        default=EventType.INFO,
        db_index=True,
    )
    event_name = models.CharField(
        max_length=100,
        help_text=_("e.g., 'FSM transition', 'Agent decision', 'Operator approval'"),
    )
    message = models.TextField()
    metadata = models.JSONField(
        default=dict,
        help_text=_("Structured event data"),
    )

    # Attribution
    triggered_by_user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_events",
    )
    triggered_by_agent = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Agent name if event was from agent run"),
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Pipeline Event")
        verbose_name_plural = _("Pipeline Events")
        indexes = [
            models.Index(fields=["pipeline_run", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.event_type}] {self.event_name}"
