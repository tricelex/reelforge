from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution
    from server.apps.pipelines.stages.base import StageContext


def _transitive_dep_keys(
    graph: list[dict[str, Any]],
    stage_key: str,
) -> list[str]:
    """Return all ancestor stage keys for *stage_key* (transitive depends_on)."""
    by_key = {node['key']: node for node in graph}
    ordered: list[str] = []
    seen: set[str] = set()
    pending = list(by_key.get(stage_key, {}).get('depends_on', []))
    while pending:
        dep_key = pending.pop()
        if dep_key in seen:
            continue
        seen.add(dep_key)
        ordered.append(dep_key)
        pending.extend(by_key.get(dep_key, {}).get('depends_on', []))
    return ordered


# Channel reverse relations read by async Stage.run() — preload in build_context
# to avoid SynchronousOnlyOperation from lazy ORM fetches.
_CHANNEL_RELATIONS = (
    'channel',
    'channel__niche_config',
    'channel__niche_config__format',
    'channel__branding',
    'channel__branding__watermark',
    'channel__assembly_style',
    'channel__footage_sourcing',
)


async def build_context(execution: 'StageExecution') -> 'StageContext':
    """Assemble a StageContext from a StageExecution row.

    Resolves channel, upstream outputs, PromptRenderer, CostRecorder,
    and AssetWriter. Config comes from the stage node in blueprint_snapshot.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.asset_writer import (  # noqa: PLC0415
        AssetWriter,
    )
    from server.apps.pipelines.services.cost_recorder import (  # noqa: PLC0415
        CostRecorder,
    )
    from server.apps.pipelines.services.prompt_renderer import (  # noqa: PLC0415
        PromptRenderer,
    )
    from server.apps.pipelines.stages.base import StageContext  # noqa: PLC0415

    run = await (
        PipelineRun.objects
        .select_related(*_CHANNEL_RELATIONS)
        .prefetch_related('channel__niche_config__format_pool')
        .aget(id=execution.run_id)
    )
    channel = run.channel

    graph: list[dict[str, Any]] = run.blueprint_snapshot.get('stages', [])
    stage_node: dict[str, Any] = next(
        (n for n in graph if n['key'] == execution.stage_key),
        {},
    )
    base_config: dict[str, Any] = stage_node.get('config', {})
    channel_overrides = channel.config_overrides or {}
    stage_overrides = channel_overrides.get(execution.stage_key, {})
    if not isinstance(stage_overrides, dict):
        stage_overrides = {}
    config: dict[str, Any] = {**base_config, **stage_overrides}

    deps = _transitive_dep_keys(graph, execution.stage_key)
    upstream: dict[str, Any] = {}
    for dep_key in deps:
        dep_exec = await (
            StageExecution.objects
            .filter(
                run=run,
                stage_key=dep_key,
                status=StageStatus.SUCCEEDED,
                parent=None,
            )
            .order_by('-attempt')
            .afirst()
        )
        if dep_exec is not None:
            upstream[dep_key] = dep_exec.output

    return StageContext(
        run=run,
        execution=execution,
        channel=channel,
        config=config,
        upstream=upstream,
        prompts=PromptRenderer(run.prompt_snapshot),
        costs=CostRecorder(execution),
        assets=AssetWriter(execution),
    )
