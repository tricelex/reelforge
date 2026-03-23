from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.***REMOVED***.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django_fsm import FSMField
from django_fsm import transition

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import SocialAccount
from ***REMOVED***.core.models import BaseAbstractModel

if TYPE_CHECKING:
    from collections.abc import Iterable


class ClippingJob(BaseAbstractModel):
    class Status(models.TextChoices):
        INITIALIZING = "INITIALIZING", "Initializing"
        DOWNLOADING = "DOWNLOADING", "Downloading"
        TRANSCRIBING = "TRANSCRIBING", "Transcribing"
        ANALYZING = "ANALYZING", "Analyzing"
        AWAITING_CLIP_APPROVAL = "AWAITING_CLIP_APPROVAL", "Awaiting Clip Approval"
        RENDERING = "RENDERING", "Rendering"
        DISTRIBUTING = "DISTRIBUTING", "Distributing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        PAUSED = "PAUSED", "Paused"

    class SourceType(models.TextChoices):
        YOUTUBE_URL = "YOUTUBE_URL", "YouTube URL"
        DIRECT_URL = "DIRECT_URL", "Direct URL"
        UPLOAD = "UPLOAD", "File Upload"

    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="clipping_jobs",
    )
    target_accounts = models.ManyToManyField(
        SocialAccount,
        blank=True,
        related_name="clipping_jobs",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.YOUTUBE_URL,
    )
    source_url = models.URLField(blank=True)
    source_video_file = models.FileField(
        upload_to="clipping/source/",
        blank=True,
        null=True,
    )
    downloaded_file = models.FileField(
        upload_to="clipping/downloaded/",
        blank=True,
        null=True,
    )
    source_title = models.CharField(max_length=500, blank=True)
    source_duration_sec = models.PositiveIntegerField(null=True, blank=True)

    # Transcription
    transcript_text = models.TextField(blank=True)
    transcript_json = models.JSONField(default=dict, blank=True)
    transcription_provider = models.CharField(max_length=50, blank=True)
    transcription_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal("0"),
    )

    # Analysis
    clips_requested = models.PositiveIntegerField(default=5)
    analysis_provider = models.CharField(max_length=50, blank=True)
    analysis_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal("0"),
    )

    # Agent
    agent_run_id = models.CharField(max_length=255, blank=True)
    agent_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal("0"),
    )

    # Task tracking
    celery_task_id = models.CharField(max_length=255, blank=True)

    # FSM
    status = FSMField(
        default=Status.INITIALIZING,
        protected=True,
        choices=Status.choices,
    )

    # Timeline
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Clipping Job"
        verbose_name_plural = "Clipping Jobs"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["channel"]),
        ]

    def __str__(self) -> str:
        return f"Clip: {self.source_title[:60] or self.source_url[:60]}"

    def refresh_from_db(
        self,
        using: str | None = None,
        fields: Iterable[str] | None = None,
        from_queryset: models.QuerySet | None = None,
    ) -> None:
        """Override to allow refresh_from_db() to work with protected FSMField.

        django_fsm FSMField(protected=True) blocks setattr() once the field is in
        __dict__. refresh_from_db() calls setattr() internally, which raises
        AttributeError. We temporarily remove the status key from __dict__ so the
        FSM descriptor's protection check is bypassed during the refresh.
        """
        fsm_field_names = [f.name for f in self._meta.concrete_fields if isinstance(f, FSMField)]
        for name in fsm_field_names:
            self.__dict__.pop(name, None)
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)

    @property
    def total_cost_usd(self) -> Decimal:
        return self.transcription_cost_usd + self.analysis_cost_usd

    # --- FSM transitions ---

    @transition(field=status, source=Status.INITIALIZING, target=Status.DOWNLOADING)
    def begin_download(self) -> None:
        self.started_at = timezone.now()

    @transition(field=status, source=Status.DOWNLOADING, target=Status.TRANSCRIBING)
    def begin_transcription(self) -> None:
        pass

    @transition(field=status, source=Status.TRANSCRIBING, target=Status.ANALYZING)
    def begin_analysis(self) -> None:
        pass

    @transition(field=status, source=Status.ANALYZING, target=Status.AWAITING_CLIP_APPROVAL)
    def await_clip_approval(self) -> None:
        pass

    @transition(
        field=status,
        source=[Status.ANALYZING, Status.AWAITING_CLIP_APPROVAL],
        target=Status.RENDERING,
    )
    def begin_rendering(self) -> None:
        pass

    @transition(field=status, source=Status.RENDERING, target=Status.DISTRIBUTING)
    def begin_distribution(self) -> None:
        pass

    @transition(field=status, source=Status.DISTRIBUTING, target=Status.COMPLETED)
    def mark_completed(self) -> None:
        self.completed_at = timezone.now()

    @transition(field=status, source="*", target=Status.FAILED)
    def mark_failed(self, error: str = "", trace: str = "") -> None:
        self.last_error = error
        self.failed_at = timezone.now()

    @transition(
        field=status,
        source=[
            Status.DOWNLOADING,
            Status.TRANSCRIBING,
            Status.ANALYZING,
            Status.AWAITING_CLIP_APPROVAL,
            Status.RENDERING,
            Status.DISTRIBUTING,
        ],
        target=Status.PAUSED,
    )
    def pause(self) -> None:
        pass

    @transition(field=status, source=Status.PAUSED, target=Status.AWAITING_CLIP_APPROVAL)
    def resume_to_approval(self) -> None:
        pass

    @transition(field=status, source=Status.PAUSED, target=Status.RENDERING)
    def resume_to_rendering(self) -> None:
        pass


class ClipCandidate(BaseAbstractModel):
    class CandidateStatus(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        RENDERING = "RENDERING", "Rendering"
        RENDERED = "RENDERED", "Rendered"
        DISTRIBUTING = "DISTRIBUTING", "Distributing"
        DISTRIBUTED = "DISTRIBUTED", "Distributed"

    clipping_job = models.ForeignKey(
        ClippingJob,
        on_delete=models.CASCADE,
        related_name="candidates",
    )
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    title = models.CharField(max_length=200)
    hook_text = models.CharField(max_length=200, blank=True)
    caption_template = models.TextField(blank=True)
    relevance_score = models.FloatField(default=0.0)
    reason = models.TextField(blank=True)
    transcript_excerpt = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=CandidateStatus.choices,
        default=CandidateStatus.PROPOSED,
    )
    approved = models.BooleanField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_clip_candidates",
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-relevance_score"]
        verbose_name = "Clip Candidate"
        verbose_name_plural = "Clip Candidates"

    def __str__(self) -> str:
        return f"{self.title[:50]} ({self.start_sec:.0f}s\u2013{self.end_sec:.0f}s)"

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def clean(self) -> None:
        super().clean()
        if self.end_sec <= self.start_sec:
            raise ValidationError("end_sec must be greater than start_sec")
        duration = self.end_sec - self.start_sec
        if duration < 30:
            raise ValidationError(
                f"Clip duration {duration:.1f}s is below minimum 30s"
            )
        if duration > 180:
            raise ValidationError(
                f"Clip duration {duration:.1f}s exceeds maximum 180s"
            )
        # Overlap detection (±1s tolerance for frame precision)
        # Use pk=0 fallback so .exclude() works correctly for unsaved records (pk=None)
        overlapping = ClipCandidate.objects.filter(
            clipping_job=self.clipping_job,
            start_sec__lt=self.end_sec + 1,
            end_sec__gt=self.start_sec - 1,
        ).exclude(pk=self.pk or 0)
        if overlapping.exists():
            other = overlapping.first()
            raise ValidationError(
                f"Clip overlaps with existing candidate '{other.title}' "
                f"({other.start_sec:.0f}s\u2013{other.end_sec:.0f}s)"
            )


class ClipRender(BaseAbstractModel):
    class Format(models.TextChoices):
        VERTICAL_9_16 = "VERTICAL_9_16", "Vertical 9:16"
        LANDSCAPE_16_9 = "LANDSCAPE_16_9", "Landscape 16:9"
        SQUARE_1_1 = "SQUARE_1_1", "Square 1:1"

    class RenderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="renders",
    )
    format = models.CharField(
        max_length=20,
        choices=Format.choices,
        default=Format.VERTICAL_9_16,
    )
    video_file = models.FileField(
        upload_to="clipping/renders/",
        blank=True,
        null=True,
    )
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    include_captions = models.BooleanField(default=True)
    include_title_card = models.BooleanField(default=True)
    include_branding = models.BooleanField(default=True)
    render_config = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=RenderStatus.choices,
        default=RenderStatus.PENDING,
    )
    celery_task_id = models.CharField(max_length=255, blank=True)
    render_duration_sec = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Clip Render"
        verbose_name_plural = "Clip Renders"

    def __str__(self) -> str:
        return f"Render {self.format} \u2014 {self.candidate}"


class ClipPost(BaseAbstractModel):
    class PostStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        POSTING = "POSTING", "Posting"
        POSTED = "POSTED", "Posted"
        SCHEDULED = "SCHEDULED", "Scheduled"
        FAILED = "FAILED", "Failed"

    render = models.ForeignKey(
        ClipRender,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    social_account = models.ForeignKey(
        SocialAccount,
        on_delete=models.CASCADE,
        related_name="clip_posts",
    )
    caption = models.TextField(blank=True)
    title = models.CharField(max_length=200, blank=True)
    hashtags = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PostStatus.choices,
        default=PostStatus.PENDING,
    )
    platform_post_id = models.CharField(max_length=255, blank=True)
    platform_url = models.URLField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)

    # Performance metrics
    views = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    revenue_est_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("0"),
    )
    last_analytics_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Clip Post"
        verbose_name_plural = "Clip Posts"

    def __str__(self) -> str:
        return f"{self.social_account.get_platform_display()} post \u2014 {self.render}"
