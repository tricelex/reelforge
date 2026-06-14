from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution
    from server.apps.pipelines.stages.base import StageContext


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

    run = await PipelineRun.objects.select_related('channel').aget(
        id=execution.run_id,
    )
    channel = run.channel

    graph: list[dict[str, Any]] = run.blueprint_snapshot.get('stages', [])
    stage_node: dict[str, Any] = next(
        (n for n in graph if n['key'] == execution.stage_key),
        {},
    )
    config: dict[str, Any] = stage_node.get('config', {})

    deps: list[str] = stage_node.get('depends_on', [])
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
