from __future__ import annotations

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import action
from unfold.decorators import display

from ***REMOVED***.scripts.models import ScriptJob
from ***REMOVED***.scripts.models import ScriptRevision


class ScriptRevisionInline(TabularInline):
    model = ScriptRevision
    extra = 0
    fields = [
        "version_number",
        "word_count",
        "change_summary",
        "changed_by",
        "created_at",
    ]
    readonly_fields = ["version_number", "word_count", "created_at"]
    autocomplete_fields = ["changed_by"]
    ordering = ["-version_number"]


@admin.register(ScriptJob)
class ScriptJobAdmin(ModelAdmin):
    list_display = [
        "id",
        "channel_name",
        "status_badge",
        "script_title",
        "approved",
        "auto_approved",
        "word_count",
        "hook_score_display",
        "readability_score_display",
        "created_at",
        "duration_display",
        "cost_display",
    ]
    list_filter = [
        "status",
        "approved",
        "auto_approved",
        "created_at",
        "channel",
        "category",
    ]
    search_fields = [
        "id",
        "final_title",
        "topic__title_idea",
        "script_text",
        "channel__name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "duration_seconds",
        "celery_task_id",
        "agent_run_id",
        "agent_tokens_used",
        "agent_cost_usd",
        "word_count",
        "estimated_duration_mins",
        "approved_at",
        "revision_count",
        "selected_hook",
        "total_segments",
        "broll_count",
        "readability_score",
        "script_preview",
        "hook_preview",
        "seo_preview",
    ]
    autocomplete_fields = ["channel", "topic", "approved_by"]
    inlines = [ScriptRevisionInline]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "topic",
                    "status",
                ),
            },
        ),
        (
            _("Research Data"),
            {
                "classes": ("collapse",),
                "fields": (
                    "research_data",
                    "research_sources",
                ),
            },
        ),
        (
            _("Hooks (Agent Generated Options)"),
            {
                "fields": (
                    "generated_hooks",
                    "selected_hook_idx",
                    "selected_hook",
                    "hook_score",
                ),
            },
        ),
        (
            _("Script Content"),
            {
                "fields": (
                    "script_text",
                    "script_version",
                    "script_file",
                    "word_count",
                    "estimated_duration_mins",
                ),
            },
        ),
        (
            _("Script Structure"),
            {
                "classes": ("collapse",),
                "fields": ("main_points",),
            },
        ),
        (
            _("QA Results"),
            {
                "classes": ("collapse",),
                "fields": (
                    "readability_score",
                    "qa_issues_found",
                    "qa_issues_fixed",
                ),
            },
        ),
        (
            _("SEO Metadata"),
            {
                "fields": (
                    "final_title",
                    "final_description",
                    "seo_tags",
                    "category",
                    "chapters",
                    "pinned_comment",
                ),
            },
        ),
        (
            _("B-Roll Suggestions (Structured)"),
            {
                "classes": ("collapse",),
                "fields": (
                    "broll_suggestions",
                    "broll_count",
                ),
            },
        ),
        (
            _("TTS Segments (Pre-chunked)"),
            {
                "classes": ("collapse",),
                "fields": (
                    "segments",
                    "total_segments",
                ),
            },
        ),
        (
            _("Approval"),
            {
                "fields": (
                    "approved",
                    "approved_at",
                    "approved_by",
                    "auto_approved",
                    "rejection_reason",
                ),
            },
        ),
        (
            _("Agent Execution"),
            {
                "classes": ("collapse",),
                "fields": (
                    "agent_run_id",
                    "agent_tokens_used",
                    "agent_cost_usd",
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
                    "duration_seconds",
                ),
            },
        ),
        (
            _("Revisions"),
            {
                "classes": ("collapse",),
                "fields": ("revision_count",),
            },
        ),
        (
            _("Notes"),
            {
                "classes": ("collapse",),
                "fields": ("notes",),
            },
        ),
    )

    @display(
        description=_("Status"),
        ordering="status",
        label={
            "PENDING": "default",
            "QUEUED": "info",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "RETRYING": "warning",
            "PAUSED": "warning",
            "REJECTED": "default",
            "SKIPPED": "default",
        },
    )
    def status_badge(self, obj: ScriptJob) -> str:
        return obj.status

    @display(description=_("Hook Score"), ordering="hook_score")
    def hook_score_display(self, obj: ScriptJob) -> str:
        return f"{obj.hook_score:.1f}/10"

    @display(description=_("Readability"), ordering="readability_score")
    def readability_score_display(self, obj: ScriptJob) -> str:
        if obj.readability_score > 0:
            return f"{obj.readability_score:.1f}/10"
        return "-"

    @display(description=_("Duration"))
    def duration_display(self, obj: ScriptJob) -> str:
        if obj.duration_seconds:
            return f"{obj.duration_seconds}s"
        return "-"

    @display(description=_("Cost"), ordering="agent_cost_usd")
    def cost_display(self, obj: ScriptJob) -> str:
        return f"${obj.agent_cost_usd:.4f}"

    @display(description=_("Script Title"))
    def script_title(self, obj: ScriptJob) -> str:
        """Display script title."""
        return obj.final_title or obj.topic.title_idea[:60]

    @display(description=_("Channel"), ordering="channel__name")
    def channel_name(self, obj: ScriptJob) -> str:
        """Display channel name."""
        return obj.channel.name

    @display(description=_("Script Preview"))
    def script_preview(self, obj: ScriptJob) -> str:
        """Preview of script text in admin."""
        if obj.script_text:
            return format_html(
                '<div style="max-height:300px;overflow-y:auto;white-space:pre-wrap;'
                'font-size:12px;background:#f9f9f9;padding:10px;border-radius:4px">{}</div>',
                obj.script_text[:2000],
            )
        return "No script yet"

    @display(description=_("Hook Preview"))
    def hook_preview(self, obj: ScriptJob) -> str:
        """Preview of selected hook."""
        hook = obj.selected_hook
        if hook:
            return format_html(
                '<div style="max-height:100px;overflow-y:auto;white-space:pre-wrap;'
                'font-size:12px;background:#fffef0;padding:8px;border-radius:4px">'
                "<strong>Score: {:.1f}</strong><br>{}</div>",
                hook.get("score", 0),
                hook.get("text", "")[:200],
            )
        return "—"

    @display(description=_("SEO Preview"))
    def seo_preview(self, obj: ScriptJob) -> str:
        """Preview of SEO metadata."""
        tags = ", ".join(obj.seo_tags[:5]) if obj.seo_tags else "—"
        return format_html(
            '<div style="font-size:11px">'
            "<strong>Tags:</strong> {}<br>"
            "<strong>Category:</strong> {}</div>",
            tags,
            obj.category or "—",
        )

    # ── Admin Actions ──────────────────────────────────────────────────

    @action(description="✅ Approve Script")
    def approve_script(self, request, queryset):
        """Approve selected scripts and trigger asset pipeline."""
        count = 0
        for script in queryset.filter(approved=False):
            script.approved = True
            script.approved_at = timezone.now()
            script.save(update_fields=["approved", "approved_at", "updated_at"])
            # TODO: Trigger asset job when tasks are implemented
            # from ***REMOVED***.assets.tasks import run_asset_job
            # run_asset_job.delay(str(script.id))
            count += 1
        self.message_user(request, f"{count} scripts approved.")


@admin.register(ScriptRevision)
class ScriptRevisionAdmin(ModelAdmin):
    list_display = [
        "id",
        "script_job",
        "version_number",
        "word_count",
        "changed_by",
        "created_at",
    ]
    list_filter = [
        "created_at",
        "changed_by",
    ]
    search_fields = [
        "id",
        "script_job__final_title",
        "script_text",
        "change_summary",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = ["script_job", "changed_by"]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "script_job",
                    "version_number",
                ),
            },
        ),
        (
            _("Content"),
            {
                "fields": (
                    "script_text",
                    "word_count",
                ),
            },
        ),
        (
            _("Changes"),
            {
                "fields": (
                    "change_summary",
                    "changed_by",
                    "agent_feedback",
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
