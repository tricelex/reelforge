from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField
from django_fsm import transition

if TYPE_CHECKING:
    from collections.abc import Iterable


class PipelineStatusChoices(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    QUEUED = "QUEUED", _("Queued")
    RUNNING = "RUNNING", _("Running")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    RETRYING = "RETRYING", _("Retrying")
    PAUSED = "PAUSED", _("Paused (Manual Review)")
    REJECTED = "REJECTED", _("Rejected")
    SKIPPED = "SKIPPED", _("Skipped")


class BaseAbstractModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    objects = models.Manager()

    class Meta:
        abstract = True

    def save(
        self,
        force_insert: bool = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Override save for triggering updated_at on update_fields case."""
        listed_for_update_fields = None
        if update_fields:
            listed_for_update_fields = list(update_fields)
            listed_for_update_fields.append("updated_at")

        return super().save(force_insert, force_update, using, listed_for_update_fields or None)


class PipelineStageModel(BaseAbstractModel):
    """Base for all pipeline stage models.
    Uses Django FSM-2 for enforced, validated state transitions.
    Replaces manual mark_*() methods with @transition-decorated methods
    that raise TransitionNotAllowed if called from an invalid state.
    """

    # FSMField replaces plain CharField — enforces valid transitions at DB level
    status = FSMField(
        default=PipelineStatusChoices.PENDING,
        choices=PipelineStatusChoices,
        protected=True,  # Prevents direct assignment: obj.status = "X" raises exception
        db_index=True,
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    max_retries = models.PositiveSmallIntegerField(default=3)
    last_error = models.TextField(blank=True)
    error_trace = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    notes = models.TextField(blank=True, help_text="Operator notes")

    # Agent execution metadata
    agent_run_id = models.CharField(max_length=255, blank=True)
    agent_tokens_used = models.PositiveIntegerField(default=0)
    agent_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        abstract = True

    # ── FSM Transitions ────────────────────────────────────────────────────
    # @transition enforces: only callable from listed source states.
    # Calling from any other state raises django_fsm.TransitionNotAllowed.
    # on_error: auto-transition to FAILED if an exception is raised inside.

    @transition(
        field=status,
        source=PipelineStatusChoices.PENDING,
        target=PipelineStatusChoices.RUNNING,
        on_error=PipelineStatusChoices.FAILED,
    )
    def start(self, task_id: str = "") -> None:
        """Transition PENDING → RUNNING. Called when Celery task picks up the job."""
        self.started_at = timezone.now()
        self.celery_task_id = task_id

    @transition(
        field=status,
        source=[PipelineStatusChoices.QUEUED],
        target=PipelineStatusChoices.RUNNING,
        on_error=PipelineStatusChoices.FAILED,
    )
    def start_from_queue(self, task_id: str = "") -> None:
        """Transition QUEUED → RUNNING."""
        self.started_at = timezone.now()
        self.celery_task_id = task_id

    @transition(
        field=status,
        source=[PipelineStatusChoices.RUNNING, PipelineStatusChoices.RETRYING],
        target=PipelineStatusChoices.COMPLETED,
    )
    def complete(self) -> None:
        """Transition RUNNING/RETRYING → COMPLETED."""
        self.completed_at = timezone.now()

    @transition(field=status, source="*", target=PipelineStatusChoices.FAILED)
    def fail(self, error: str, trace: str = "") -> None:
        """Transition any state → FAILED. Captures error detail."""
        self.last_error = error[:2000]
        self.error_trace = trace[:10000]

    @transition(field=status, source="*", target=PipelineStatusChoices.PAUSED)
    def pause(self, reason: str = "") -> None:
        """Transition any state → PAUSED. Requires human intervention to resume."""
        self.notes = reason

    @transition(
        field=status,
        source=[PipelineStatusChoices.FAILED, PipelineStatusChoices.PAUSED],
        target=PipelineStatusChoices.RETRYING,
        conditions=[lambda self: self.can_retry()],
    )
    def retry(self) -> None:
        """Transition FAILED/PAUSED → RETRYING.
        conditions=[can_retry] means FSM will refuse the transition if
        retry_count >= max_retries — no manual guard needed.
        """
        self.retry_count += 1
        self.last_error = ""
        self.started_at = timezone.now()

    @transition(field=status, source=PipelineStatusChoices.PENDING, target=PipelineStatusChoices.QUEUED)
    def enqueue(self) -> None:
        """Transition PENDING → QUEUED when added to Celery queue."""

    @transition(field=status, source="*", target=PipelineStatusChoices.REJECTED)
    def reject(self, reason: str = "") -> None:
        """Manual rejection by operator."""
        self.notes = reason

    # ── Helpers ────────────────────────────────────────────────────────────

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def mark_running(self, task_id: str = "") -> None:
        """Convenience wrapper — handles PENDING or QUEUED source state."""
        if self.status == self.QUEUED:
            self.start_from_queue(task_id=task_id)
        else:
            self.start(task_id=task_id)
        self.save()

    def mark_completed(self) -> None:
        self.complete()
        self.save()

    def mark_failed(self, error: str, trace: str = "") -> None:
        self.fail(error=error, trace=trace)
        self.save()

    def mark_paused(self, reason: str = "") -> None:
        self.pause(reason=reason)
        self.save()

    def increment_retry(self) -> None:
        self.retry()
        self.save()

    @property
    def available_transitions(self) -> list[str]:
        """Returns transition names valid from current state. Used by Unfold admin."""
        from django_fsm import get_available_user_transitions

        return [t.name for t in get_available_user_transitions(self)]

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None
