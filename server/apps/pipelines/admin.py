from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.pipelines.models import (
    CostRecord,
    PipelineBlueprint,
    PipelineRun,
    RunCast,
    StageExecution,
)


class StageExecutionInline(TabularInline):
    model = StageExecution
    extra = 0
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


class CostRecordInline(TabularInline):
    model = CostRecord
    extra = 0
    fields = ('provider', 'operation', 'units', 'unit_cost_usd', 'total_usd')
    readonly_fields = (
        'provider',
        'operation',
        'units',
        'unit_cost_usd',
        'total_usd',
    )


class RunCastInline(TabularInline):
    model = RunCast
    extra = 0
    fields = ('character', 'role', 'is_ephemeral', 'design_status')


@admin.register(PipelineBlueprint)
class PipelineBlueprintAdmin(ModelAdmin):
    list_display = ('name', 'kind', 'version', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('name',)


@admin.register(PipelineRun)
class PipelineRunAdmin(ModelAdmin):
    list_display = ('id', 'channel', 'status', 'total_cost_usd', 'created_at')
    list_filter = ('status',)
    search_fields = ('topic', 'channel__name')
    readonly_fields = (
        'blueprint_snapshot',
        'prompt_snapshot',
        'total_cost_usd',
    )
    inlines = [RunCastInline, StageExecutionInline]


@admin.register(CostRecord)
class CostRecordAdmin(ModelAdmin):
    list_display = ('stage_execution', 'provider', 'operation', 'total_usd')
    list_filter = ('provider',)
    search_fields = ('provider', 'operation')
