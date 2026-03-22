from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.db import transaction
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_fsm import can_proceed
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import action
from unfold.decorators import display

from ***REMOVED***.core.admin import FSMModelAdminMixin
from ***REMOVED***.pipeline.choices import PipelineStatus
from ***REMOVED***.pipeline.models import PipelineEvent
from ***REMOVED***.pipeline.models import PipelineRun

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class PipelineEventInline(TabularInline):
    model = PipelineEvent
    extra = 0
    fields = [
        "created_at",
        "event_type_badge",
        "event_name",
        "message",
        "triggered_by_agent",
    ]
    readonly_fields = ["created_at", "event_type_badge", "event_name", "message", "triggered_by_agent"]
    ordering = ["created_at"]

    def has_add_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    @display(
        description=_("Type"),
        label={
            "INFO": "info",
            "SUCCESS": "success",
            "WARNING": "warning",
            "ERROR": "danger",
            "RETRY": "warning",
            "MANUAL": "default",
        },
    )
    def event_type_badge(self, obj: PipelineEvent) -> str:
        return obj.event_type


@admin.register(PipelineRun)
class PipelineRunAdmin(FSMModelAdminMixin, ModelAdmin):
    list_display = [
        "channel",
        "stage_progress",
        "overall_status_badge",
        "pipeline_title",
        "youtube_link",
        "thumbnail_preview_display",
        "total_cost_display",
        "duration_display",
        "created_at",
    ]
    list_filter = [
        "overall_status",
        "created_at",
        "channel",
    ]
    search_fields = [
        "id",
        "final_video_title",
        "channel__name",
        "orchestrator_run_id",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "failed_at",
        "orchestrator_turns",
        "total_agent_cost_usd",
        "total_asset_cost_usd",
        "total_cost_usd",
        "final_video_url",
        "final_video_duration_seconds",
        "duration_hours",
        "available_transitions",
        "fsm_actions_display",
    ]
    autocomplete_fields = [
        "channel",
        "research_job",
        "topic",
        "script_job",
        "asset_job",
        "production_job",
        "distribution_job",
    ]
    actions = [
        "start_pipeline",
        "advance_to_scripting",
        "approve_to_assets",
        "begin_rendering_action",
        "begin_upload_action",
        "retry_scripting_action",
        "retry_assets_action",
        "retry_rendering_action",
        "retry_upload_action",
        "resume_to_assets_action",
        "resume_to_rendering_action",
        "resume_to_upload_action",
        "trigger_research_action",
        "trigger_scripting_action",
        "trigger_assets_action",
        "pause_action",
        "reject_run",
        "rerun_script_with_changes_action",
    ]
    inlines = [PipelineEventInline]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "overall_status",
                    "available_transitions",
                ),
            },
        ),
        (
            _("Stage Job Links"),
            {
                "fields": (
                    "research_job",
                    "topic",
                    "script_job",
                    "asset_job",
                    "production_job",
                    "distribution_job",
                ),
            },
        ),
        (
            _("Orchestrator Context"),
            {
                "classes": ("collapse",),
                "fields": (
                    "orchestrator_run_id",
                    "orchestrator_turns",
                    "last_agent_decision",
                ),
            },
        ),
        (
            _("Costs"),
            {
                "fields": (
                    "total_agent_cost_usd",
                    "total_asset_cost_usd",
                    "total_cost_usd",
                ),
            },
        ),
        (
            _("Final Video Info"),
            {
                "fields": (
                    "final_video_title",
                    "final_video_url",
                    "final_video_duration_seconds",
                ),
            },
        ),
        (
            _("Timeline"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "started_at",
                    "completed_at",
                    "failed_at",
                    "duration_hours",
                ),
            },
        ),
    )

    @display(
        description=_("Status"),
        ordering="overall_status",
        label={
            "INITIALIZING": "default",
            "RESEARCHING": "info",
            "SCRIPTING": "info",
            "AWAITING_APPROVAL": "warning",
            "SCENE_BREAKDOWN": "info",
            "GENERATING_ASSETS": "info",
            "AUDIO_MIX": "info",
            "CLIP_GENERATION": "info",
            "RENDERING": "info",
            "QA": "info",
            "UPLOADING": "info",
            "PUBLISHED": "success",
            "FAILED": "danger",
            "PAUSED": "warning",
        },
    )
    def overall_status_badge(self, obj: PipelineRun) -> str:
        return obj.overall_status

    @display(description=_("Title"))
    def pipeline_title(self, obj: PipelineRun) -> str:
        """Display run title from final_video_title or topic."""
        return obj.final_video_title or (obj.topic.title_idea[:60] if obj.topic else "Untitled")

    @display(description=_("Pipeline Progress"))
    def stage_progress(self, obj: PipelineRun) -> str:
        """Visual progress indicator with filled/empty circles."""
        stages = ["RESEARCHING", "SCRIPTING", "GENERATING_ASSETS", "RENDERING", "QA", "UPLOADING", "PUBLISHED"]
        current_idx = stages.index(obj.current_stage) if obj.current_stage in stages else -1
        filled = "●" * (current_idx + 1)
        empty = "○" * (len(stages) - current_idx - 1)
        return format_html(
            '<span style="font-family:monospace;color:#4CAF50">{}</span>'
            '<span style="font-family:monospace;color:#ccc">{}</span> {}/{}',
            filled,
            empty,
            max(current_idx + 1, 0),
            len(stages),
        )

    @display(description=_("YouTube"))
    def youtube_link(self, obj: PipelineRun) -> str:
        """YouTube video link with play icon."""
        if obj.final_video_url:
            return format_html('<a href="{}" target="_blank">▶ Watch</a>', obj.final_video_url)
        return "—"

    @display(description=_("Thumbnail"))
    def thumbnail_preview_display(self, obj: PipelineRun) -> str:
        """Thumbnail image preview."""
        if obj.asset_job and obj.asset_job.selected_thumbnail:
            return format_html(
                '<img src="{}" style="max-height:80px;border-radius:4px">',
                obj.asset_job.selected_thumbnail.url,
            )
        return "—"

    @display(description=_("Total Cost"), ordering="total_agent_cost_usd")
    def total_cost_display(self, obj: PipelineRun) -> str:
        return f"${obj.total_cost_usd:.4f}"

    @display(description=_("Duration"))
    def duration_display(self, obj: PipelineRun) -> str:
        if obj.duration_hours:
            return f"{obj.duration_hours:.1f}h"
        return "-"

    @display(description=_("Available Actions"))
    def fsm_actions_display(self, obj: PipelineRun) -> str:
        """Show what FSM transitions are available for this run — always accurate."""
        transitions = obj.available_transitions
        if not transitions:
            return "—"
        badges = " ".join(
            f'<span style="background:#e0e0e0;padding:2px 6px;border-radius:3px;font-size:11px">{t}</span>'
            for t in transitions
        )
        return format_html(badges)

    # ── Admin Actions ──────────────────────────────────────────────────

    @action(description="▶ Start Pipeline")
    def start_pipeline(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Advance INITIALIZING → RESEARCHING, create ResearchJob if needed, and dispatch research task."""
        from ***REMOVED***.pipeline.tasks import run_research_job
        from ***REMOVED***.research.choices import ResearchTrigger
        from ***REMOVED***.research.models import ResearchJob

        count = 0
        for run in queryset:
            if can_proceed(run.begin_research):
                if not run.research_job:
                    research_job = ResearchJob.objects.create(
                        channel=run.channel,
                        trigger_source=ResearchTrigger.MANUAL,
                        search_keywords=list(run.channel.channel_keywords[:10]),
                    )
                    run.research_job = research_job
                run.begin_research()
                run.save()
                channel_id = str(run.channel.id)
                research_job_id = str(run.research_job.id)
                transaction.on_commit(lambda cid=channel_id, rjid=research_job_id: run_research_job.delay(cid, rjid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot start '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) started.")

    @action(description="⏭ Advance to Scripting")
    def advance_to_scripting(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Advance RESEARCHING → SCRIPTING and dispatch script task."""
        from ***REMOVED***.pipeline.tasks import run_script_job

        count = 0
        for run in queryset:
            if can_proceed(run.begin_scripting):
                if not run.topic:
                    self.message_user(
                        request,
                        f"'{run}' has no topic set — scripting task will not be dispatched.",
                        level="WARNING",
                    )
                run.begin_scripting()
                run.save()
                if run.topic:
                    topic_id = str(run.topic.id)
                    run_id = str(run.id)
                    transaction.on_commit(lambda tid=topic_id, rid=run_id: run_script_job.delay(tid, rid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot advance '{run}' to scripting — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) advanced to scripting.")

    @action(description="▶ Approve & Continue to Assets")
    def approve_to_assets(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Transition AWAITING_APPROVAL → SCENE_BREAKDOWN → GENERATING_ASSETS via scene breakdown task.

        Also handles runs already in GENERATING_ASSETS that are missing a SceneBreakdownJob —
        skips the FSM transition and dispatches the breakdown task directly.
        """
        from ***REMOVED***.pipeline.tasks import run_scene_breakdown_job
        from ***REMOVED***.production.models import SceneBreakdownJob

        count = 0
        for run in queryset:
            allowed_states = {PipelineStatus.AWAITING_APPROVAL, PipelineStatus.GENERATING_ASSETS}
            if run.overall_status not in allowed_states:
                self.message_user(
                    request,
                    f"Cannot approve '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
                continue
            if not run.script_job:
                self.message_user(
                    request,
                    f"'{run}' has no script_job set — cannot start scene breakdown.",
                    level="WARNING",
                )
                continue

            if can_proceed(run.begin_scene_breakdown):
                run.begin_scene_breakdown()
                run.save(update_fields=["overall_status", "current_stage", "updated_at"])

            breakdown_job, _ = SceneBreakdownJob.objects.get_or_create(script_job=run.script_job)
            if run.scene_breakdown_job_id != breakdown_job.id:
                run.scene_breakdown_job = breakdown_job
                run.save(update_fields=["scene_breakdown_job", "updated_at"])

            job_id = str(breakdown_job.id)
            run_id = str(run.id)
            transaction.on_commit(lambda jid=job_id, rid=run_id: run_scene_breakdown_job.delay(jid, rid))
            count += 1

        if count > 0:
            self.message_user(
                request,
                f"{count} run(s) dispatched to scene breakdown → asset generation.",
            )

    @action(description="🎬 Begin Rendering")
    def begin_rendering_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Advance GENERATING_ASSETS → RENDERING and dispatch render task."""
        from ***REMOVED***.pipeline.tasks import render_video

        count = 0
        for run in queryset:
            if can_proceed(run.begin_rendering):
                if not run.production_job:
                    self.message_user(
                        request,
                        f"'{run}' has no production_job set — render task will not be dispatched.",
                        level="WARNING",
                    )
                run.begin_rendering()
                run.save()
                if run.production_job:
                    production_job_id = str(run.production_job.id)
                    transaction.on_commit(lambda pjid=production_job_id: render_video.delay(pjid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot begin rendering for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) advanced to rendering.")

    @action(description="📤 Begin Upload")
    def begin_upload_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Advance QA → UPLOADING and dispatch upload task."""
        from ***REMOVED***.pipeline.tasks import upload_video

        count = 0
        for run in queryset:
            if can_proceed(run.begin_upload):
                if not run.distribution_job:
                    self.message_user(
                        request,
                        f"'{run}' has no distribution_job set — upload task will not be dispatched.",
                        level="WARNING",
                    )
                run.begin_upload()
                run.save()
                if run.distribution_job:
                    distribution_job_id = str(run.distribution_job.id)
                    transaction.on_commit(lambda djid=distribution_job_id: upload_video.delay(djid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot begin upload for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) advanced to uploading.")

    @action(description="🔄 Retry Scripting")
    def retry_scripting_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Retry scripting for failed pipelines (FAILED → SCRIPTING) and re-dispatch script task."""
        from ***REMOVED***.pipeline.tasks import run_script_job

        count = 0
        for run in queryset:
            if can_proceed(run.retry_scripting):
                run.retry_scripting()
                run.save()
                if run.topic:
                    topic_id = str(run.topic.id)
                    run_id = str(run.id)
                    transaction.on_commit(lambda tid=topic_id, rid=run_id: run_script_job.delay(tid, rid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot retry scripting for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) set to retry scripting.")

    @action(description="🔄 Retry Asset Generation")
    def retry_assets_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Retry asset generation for failed pipelines (FAILED → GENERATING_ASSETS) and re-dispatch task."""
        from ***REMOVED***.pipeline.tasks import run_asset_job

        count = 0
        for run in queryset:
            if can_proceed(run.retry_assets):
                run.retry_assets()
                run.save()
                if run.script_job:
                    script_job_id = str(run.script_job.id)
                    run_id = str(run.id)
                    transaction.on_commit(lambda sjid=script_job_id, rid=run_id: run_asset_job.delay(sjid, rid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot retry assets for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) set to retry asset generation.")

    @action(description="🔄 Retry Rendering")
    def retry_rendering_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Retry rendering for failed pipelines and re-dispatch render task."""
        from ***REMOVED***.pipeline.tasks import render_video

        count = 0
        for run in queryset:
            if can_proceed(run.retry_rendering):
                run.retry_rendering()
                run.save()
                if run.production_job:
                    production_job_id = str(run.production_job.id)
                    transaction.on_commit(lambda pjid=production_job_id: render_video.delay(pjid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot retry rendering for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} runs set to retry rendering.")

    @action(description="🔄 Retry Upload")
    def retry_upload_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Retry upload for failed pipelines (FAILED → UPLOADING) and re-dispatch upload task."""
        from ***REMOVED***.pipeline.tasks import upload_video

        count = 0
        for run in queryset:
            if can_proceed(run.retry_upload):
                run.retry_upload()
                run.save()
                if run.distribution_job:
                    distribution_job_id = str(run.distribution_job.id)
                    transaction.on_commit(lambda djid=distribution_job_id: upload_video.delay(djid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot retry upload for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) set to retry upload.")

    @action(description="▶ Resume → Assets")
    def resume_to_assets_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Resume paused pipelines to asset generation (PAUSED → GENERATING_ASSETS) and re-dispatch task."""
        from ***REMOVED***.pipeline.tasks import run_asset_job

        count = 0
        for run in queryset:
            if can_proceed(run.resume_to_assets):
                run.resume_to_assets()
                run.save()
                if run.script_job:
                    script_job_id = str(run.script_job.id)
                    run_id = str(run.id)
                    transaction.on_commit(lambda sjid=script_job_id, rid=run_id: run_asset_job.delay(sjid, rid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot resume '{run}' to assets — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) resumed to asset generation.")

    @action(description="▶ Resume → Rendering")
    def resume_to_rendering_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Resume paused pipelines to rendering (PAUSED → RENDERING) and re-dispatch render task."""
        from ***REMOVED***.pipeline.tasks import render_video

        count = 0
        for run in queryset:
            if can_proceed(run.resume_to_rendering):
                run.resume_to_rendering()
                run.save()
                if run.production_job:
                    production_job_id = str(run.production_job.id)
                    transaction.on_commit(lambda pjid=production_job_id: render_video.delay(pjid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot resume '{run}' to rendering — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) resumed to rendering.")

    @action(description="▶ Resume → Upload")
    def resume_to_upload_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Resume paused pipelines to upload (PAUSED → UPLOADING) and re-dispatch upload task."""
        from ***REMOVED***.pipeline.tasks import upload_video

        count = 0
        for run in queryset:
            if can_proceed(run.resume_to_upload):
                run.resume_to_upload()
                run.save()
                if run.distribution_job:
                    distribution_job_id = str(run.distribution_job.id)
                    transaction.on_commit(lambda djid=distribution_job_id: upload_video.delay(djid))
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot resume '{run}' to upload — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} run(s) resumed to upload.")

    # ── Re-dispatch actions (no FSM state change — re-fires task for stuck runs) ──

    @action(description="🔁 Trigger Research (re-dispatch)")
    def trigger_research_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Re-dispatch the research task for stuck RESEARCHING runs. Does not change FSM state."""
        from ***REMOVED***.pipeline.choices import PipelineStatus
        from ***REMOVED***.pipeline.tasks import run_research_job

        count = 0
        for run in queryset:
            if run.overall_status != PipelineStatus.RESEARCHING:
                self.message_user(
                    request,
                    f"'{run}' is not in RESEARCHING state (current: {run.overall_status}) — skipping.",
                    level="WARNING",
                )
                continue
            if not run.research_job:
                self.message_user(
                    request,
                    f"'{run}' has no research_job linked — cannot re-dispatch.",
                    level="ERROR",
                )
                continue
            channel_id = str(run.channel.id)
            research_job_id = str(run.research_job.id)
            transaction.on_commit(lambda cid=channel_id, rjid=research_job_id: run_research_job.delay(cid, rjid))
            count += 1
        if count > 0:
            self.message_user(request, f"{count} research task(s) re-dispatched.")

    @action(description="🔁 Trigger Scripting (re-dispatch)")
    def trigger_scripting_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Re-dispatch the script task for stuck SCRIPTING runs. Does not change FSM state."""
        from ***REMOVED***.pipeline.choices import PipelineStatus
        from ***REMOVED***.pipeline.tasks import run_script_job

        count = 0
        for run in queryset:
            if run.overall_status != PipelineStatus.SCRIPTING:
                self.message_user(
                    request,
                    f"'{run}' is not in SCRIPTING state (current: {run.overall_status}) — skipping.",
                    level="WARNING",
                )
                continue
            if not run.topic:
                self.message_user(
                    request,
                    f"'{run}' has no topic linked — cannot re-dispatch.",
                    level="ERROR",
                )
                continue
            topic_id = str(run.topic.id)
            run_id = str(run.id)
            transaction.on_commit(lambda tid=topic_id, rid=run_id: run_script_job.delay(tid, rid))
            count += 1
        if count > 0:
            self.message_user(request, f"{count} scripting task(s) re-dispatched.")

    @action(description="🔁 Trigger Assets (re-dispatch)")
    def trigger_assets_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Re-dispatch the asset task for stuck GENERATING_ASSETS runs. Does not change FSM state."""
        from ***REMOVED***.pipeline.choices import PipelineStatus
        from ***REMOVED***.pipeline.tasks import run_asset_job

        count = 0
        for run in queryset:
            if run.overall_status != PipelineStatus.GENERATING_ASSETS:
                self.message_user(
                    request,
                    f"'{run}' is not in GENERATING_ASSETS state (current: {run.overall_status}) — skipping.",
                    level="WARNING",
                )
                continue
            if not run.script_job:
                self.message_user(
                    request,
                    f"'{run}' has no script_job linked — cannot re-dispatch.",
                    level="ERROR",
                )
                continue
            script_job_id = str(run.script_job.id)
            run_id = str(run.id)
            transaction.on_commit(lambda sjid=script_job_id, rid=run_id: run_asset_job.delay(sjid, rid))
            count += 1
        if count > 0:
            self.message_user(request, f"{count} asset task(s) re-dispatched.")

    @action(description="⏸ Pause Pipeline")
    def pause_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Pause pipelines for manual intervention."""
        count = 0
        for run in queryset:
            if can_proceed(run.pause_pipeline):
                run.pause_pipeline(reason="Manually paused by operator")
                run.save()
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot pause '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} pipelines paused.")

    @action(description="🗑 Reject & Archive")
    def reject_run(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Reject and archive pipeline runs."""
        count = 0
        for run in queryset:
            if can_proceed(run.mark_failed):
                run.mark_failed(reason="Rejected by operator")
                run.save()
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot reject '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} runs rejected.")

    @action(description="🔁 Rerun Script with Changes")
    def rerun_script_with_changes_action(self, request: HttpRequest, queryset: QuerySet[PipelineRun]) -> None:
        """Re-run the ScriptAgent on the linked ScriptJob using its change_request field.
        Operator must open the ScriptJob, fill 'change_request', save, then return here.
        Does NOT change the PipelineRun FSM state.
        """
        from ***REMOVED***.pipeline.tasks import run_script_revision_job

        count = 0
        for run in queryset:
            if not run.script_job:
                self.message_user(
                    request,
                    f"'{run}' has no script_job linked — skipping.",
                    level="WARNING",
                )
                continue
            if not run.script_job.change_request.strip():
                self.message_user(
                    request,
                    f"'{run}' script_job has no change request — open the ScriptJob, "
                    "fill 'change_request', save, then retry this action.",
                    level="WARNING",
                )
                continue
            script_job_id = str(run.script_job.id)
            transaction.on_commit(lambda sjid=script_job_id: run_script_revision_job.delay(sjid))
            count += 1
        if count > 0:
            self.message_user(request, f"{count} script revision job(s) dispatched.")


@admin.register(PipelineEvent)
class PipelineEventAdmin(ModelAdmin):
    list_display = [
        "pipeline_run",
        "event_type_badge",
        "event_name",
        "message_preview",
        "triggered_by_user",
        "triggered_by_agent",
        "created_at",
    ]
    list_filter = [
        "event_type",
        "created_at",
        "triggered_by_agent",
    ]
    search_fields = [
        "id",
        "event_name",
        "message",
        "pipeline_run__id",
        "pipeline_run__final_video_title",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "pipeline_run",
        "event_type",
        "event_name",
        "message",
        "metadata",
        "triggered_by_user",
        "triggered_by_agent",
    ]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "pipeline_run",
                    "event_type",
                    "event_name",
                ),
            },
        ),
        (
            _("Event Details"),
            {
                "fields": (
                    "message",
                    "metadata",
                ),
            },
        ),
        (
            _("Attribution"),
            {
                "fields": (
                    "triggered_by_user",
                    "triggered_by_agent",
                ),
            },
        ),
        (
            _("Timestamps"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: PipelineEvent | None = None) -> bool:
        return True

    def has_delete_permission(self, request: HttpRequest, obj: PipelineEvent | None = None) -> bool:
        return True

    @display(
        description=_("Event Type"),
        ordering="event_type",
        label={
            "INFO": "info",
            "SUCCESS": "success",
            "WARNING": "warning",
            "ERROR": "danger",
            "RETRY": "warning",
            "MANUAL": "default",
        },
    )
    def event_type_badge(self, obj: PipelineEvent) -> str:
        return obj.event_type

    @display(description=_("Message"))
    def message_preview(self, obj: PipelineEvent) -> str:
        return obj.message[:100]
