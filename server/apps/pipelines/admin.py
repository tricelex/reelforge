from typing import ClassVar

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
    RangeDateFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
)

from server.apps.pipelines.models import (
    CastDesignStatus,
    CostRecord,
    PipelineBlueprint,
    PipelineRun,
    RunCast,
    StageExecution,
    StageStatus,
)
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
    make_boolean_badge_method,
    make_header_method,
    make_money_method,
)


class StageExecutionInline(TabularInline):  # type: ignore[misc]
    """Inline for stage executions on a PipelineRun."""

    model = StageExecution
    extra = 0
    tab = True
    fields = (
        'stage_key',
        'status',
        'attempt',
        'queue',
        'cost_usd',
        'started_at',
        'finished_at',
    )
    readonly_fields = (
        'stage_key',
        'status',
        'attempt',
        'queue',
        'cost_usd',
        'started_at',
        'finished_at',
    )


class CostRecordInline(TabularInline):  # type: ignore[misc]
    """Inline for cost records on a StageExecution."""

    model = CostRecord
    extra = 0
    tab = True
    fields = ('provider', 'operation', 'units', 'unit_cost_usd', 'total_usd')
    readonly_fields = (
        'provider',
        'operation',
        'units',
        'unit_cost_usd',
        'total_usd',
    )


class RunCastInline(TabularInline):  # type: ignore[misc]
    """Inline for character cast on a PipelineRun."""

    model = RunCast
    extra = 0
    tab = True
    fields = ('character', 'role', 'is_ephemeral', 'design_status')


_CAST_COLORS = {
    CastDesignStatus.PROPOSED: 'info',
    CastDesignStatus.APPROVED: 'success',
    CastDesignStatus.DEMOTED: 'danger',
}


@admin.register(PipelineBlueprint)
class PipelineBlueprintAdmin(ReelForgeAdmin):
    """Admin for PipelineBlueprint."""

    list_display = (
        'name',
        'display_kind',
        'version',
        'display_is_active',
    )
    list_filter = (
        ('kind', ChoicesCheckboxFilter),
        ('is_active', ChoicesCheckboxFilter),
    )
    search_fields = ('name',)
    fieldsets = (
        (
            None,
            {
                'fields': ('name', 'kind', 'version', 'is_active'),
            },
        ),
        (
            _('Graph'),
            {
                'classes': ('tab',),
                'fields': ('graph',),
            },
        ),
    )

    display_kind = make_badge_method(
        'kind',
        {
            'LONGFORM': 'info',
            'SHORTS': 'success',
            'CLIPPING': 'warning',
        },
        description=_('Kind'),
    )
    display_is_active = make_boolean_badge_method(
        'is_active',
        description=_('Active'),
    )


@admin.register(PipelineRun)
class PipelineRunAdmin(ReelForgeAdmin):
    """Admin for PipelineRun — track runs with stages and costs."""

    list_display = (
        'display_topic',
        'display_status',
        'display_total_cost_usd',
        'created_at',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
        ('total_cost_usd', RangeNumericFilter),
        ('created_at', RangeDateFilter),
    )
    search_fields = ('topic', 'channel__name')
    autocomplete_fields = ('channel', 'blueprint', 'source_idea')
    list_select_related = ('channel', 'blueprint')
    readonly_fields = (
        'blueprint_snapshot',
        'prompt_snapshot',
        'total_cost_usd',
        'started_at',
        'finished_at',
        'created_at',
        'updated_at',
    )
    inlines: ClassVar = [RunCastInline, StageExecutionInline]
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'channel',
                    'blueprint',
                    'topic',
                    'status',
                    'source_idea',
                    'is_paused',
                    'total_cost_usd',
                ),
            },
        ),
        (
            _('Snapshots'),
            {
                'classes': ('tab',),
                'fields': ('blueprint_snapshot', 'prompt_snapshot'),
            },
        ),
        (
            _('Timing'),
            {
                'classes': ('tab',),
                'fields': (
                    'started_at',
                    'finished_at',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )

    display_topic = make_header_method(
        'display_topic',
        _('Run'),
        lambda obj: obj.topic[:80],
        lambda obj: str(obj.channel),
        initials=lambda obj: str(obj.id)[:2].upper(),
    )
    display_status = make_badge_method(
        'status',
        STANDARD_STATUS_COLORS,
        description=_('Status'),
    )
    display_total_cost_usd = make_money_method(
        'total_cost_usd',
        description=_('Total cost'),
    )


@admin.register(StageExecution)
class StageExecutionAdmin(ReelForgeAdmin):
    """Admin for StageExecution — inspect stage attempts across runs."""

    list_display = (
        'display_stage',
        'display_status',
        'attempt',
        'display_cost_usd',
        'started_at',
        'finished_at',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('stage_key', ChoicesCheckboxFilter),
        ('run', AutocompleteSelectFilter),
        ('cost_usd', RangeNumericFilter),
        ('started_at', RangeDateTimeFilter),
    )
    search_fields = ('run__topic', 'stage_key')
    autocomplete_fields = ('run', 'parent')
    list_select_related = ('run',)
    readonly_fields = (
        'input_hash',
        'input_snapshot',
        'output',
        'error',
        'started_at',
        'finished_at',
        'created_at',
        'updated_at',
    )
    inlines: ClassVar = [CostRecordInline]
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'run',
                    'stage_key',
                    'parent',
                    'shard_index',
                    'status',
                    'attempt',
                    'max_retries',
                    'queue',
                    'cost_usd',
                    'input_hash',
                ),
            },
        ),
        (
            _('Input'),
            {
                'classes': ('tab',),
                'fields': ('input_snapshot',),
            },
        ),
        (
            _('Output'),
            {
                'classes': ('tab',),
                'fields': ('output',),
            },
        ),
        (
            _('Error'),
            {
                'classes': ('tab',),
                'fields': ('error',),
            },
        ),
        (
            _('Timing'),
            {
                'classes': ('tab',),
                'fields': (
                    'started_at',
                    'finished_at',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )

    display_stage = make_header_method(
        'display_stage',
        _('Stage'),
        lambda obj: obj.stage_key,
        lambda obj: str(obj.run),
    )
    display_status = make_badge_method(
        'status',
        {
            **STANDARD_STATUS_COLORS,
            StageStatus.QUEUED: 'info',
            StageStatus.RUNNING: 'info',
        },
        description=_('Status'),
    )
    display_cost_usd = make_money_method('cost_usd', description=_('Cost'))


@admin.register(CostRecord)
class CostRecordAdmin(ReelForgeAdmin):
    """Admin for CostRecord — view provider cost breakdowns."""

    list_display = (
        'stage_execution',
        'provider',
        'operation',
        'display_total_usd',
    )
    list_filter = (
        ('provider', ChoicesCheckboxFilter),
        ('total_usd', RangeNumericFilter),
    )
    search_fields = ('provider', 'operation')
    autocomplete_fields = ('stage_execution',)

    display_total_usd = make_money_method('total_usd', description=_('Total'))
