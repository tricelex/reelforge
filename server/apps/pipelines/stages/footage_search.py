"""Footage search stage — fan-out per scene with a fallback cascade.

Per scene: search providers in priority order, re-rank, download and
validate the winner. When nothing usable is found the query broadens, then
falls back to AI generation, and only then parks the run for an operator.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import httpx
import structlog
from asgiref.sync import sync_to_async

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.apps.generation.clients.stock.registry import (
    build_providers,
    search_candidates,
)
from server.apps.pipelines.logic.footage_rerank import (
    apply_vision_rankings,
    rank_by_metadata,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

if TYPE_CHECKING:
    from server.apps.pipelines.models import PipelineRun

logger = structlog.get_logger(__name__)

_AI_IMAGE_COST_USD = 0.035
_DOWNLOAD_TIMEOUT_S = 120.0


def _rotate_providers(names: list[str], scene_idx: int) -> list[str]:
    """Rotate the provider priority list so scenes spread across providers.

    Otherwise every scene hits the top-priority provider first, which
    exhausts its quota fast on a large fan-out and cascades the rest of
    the scenes into paid AI fallback.
    """
    if not names:
        return names
    offset = scene_idx % len(names)
    return [*names[offset:], *names[:offset]]


async def _ai_fallback_count(run: 'PipelineRun') -> int:
    """Count AI-fallback images already generated for this run."""
    from server.apps.pipelines.models import CostRecord  # noqa: PLC0415

    return await CostRecord.objects.filter(
        stage_execution__run=run,
        operation='footage_ai_fallback',
    ).acount()


async def _fetch_bytes(url: str) -> bytes:
    """Download a URL and return its bytes."""
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


async def _probe_ok(content: bytes, suffix: str) -> bool:
    """Return True when ffprobe can read the downloaded media."""
    from server.apps.rendering.ffmpeg import async_ffprobe  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        path = handle.name
    try:
        await asyncio.to_thread(Path(path).write_bytes, content)
        probe = await async_ffprobe(path)
        return bool(probe.get('streams') or probe.get('format'))
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning('footage_probe_failed', error=str(exc))
        return False
    finally:
        await asyncio.to_thread(Path(path).unlink, missing_ok=True)


async def _download_and_validate(
    candidate: FootageCandidate,
) -> tuple[bytes, str] | None:
    """Download a candidate and verify it is playable; None when unusable."""
    try:
        content = await _fetch_bytes(candidate.download_url)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning(
            'footage_download_failed',
            provider=candidate.provider,
            external_id=candidate.external_id,
            error=str(exc),
        )
        return None
    if not content:
        return None
    suffix = '.mp4' if candidate.media_type == 'video' else '.jpg'
    if not await _probe_ok(content, suffix):
        return None
    mime = 'video/mp4' if candidate.media_type == 'video' else 'image/jpeg'
    return content, mime


def _record_credit_sync(
    run_id: str,
    asset_id: str,
    scene_idx: int,
    candidate: FootageCandidate,
) -> None:
    """Persist a FootageCredit row for a selected candidate."""
    from server.apps.assets.models import FootageCredit  # noqa: PLC0415

    FootageCredit.objects.create(
        asset_id=asset_id,
        run_id=run_id,
        scene_idx=scene_idx,
        provider=candidate.provider,
        license=candidate.license,
        license_url=candidate.license_url,
        author=candidate.author,
        source_url=candidate.source_page_url,
        title=candidate.title,
        attribution_required=candidate.attribution_required,
    )


_record_credit = sync_to_async(_record_credit_sync)


async def _vision_rank(
    ctx: StageContext,
    candidates: list[FootageCandidate],
    visual_concept: str,
) -> tuple[list[FootageCandidate], dict[str, float]]:
    """Score candidate thumbnails against the scene concept with a VLM.

    Returns the reordered candidates plus their scores keyed by
    ``external_id`` so the selected item's confidence reaches the review UI.
    """
    from pydantic_ai import Agent, ImageUrl  # noqa: PLC0415

    from server.apps.generation.clients import (  # noqa: PLC0415
        llm as llm_client,
    )
    from server.apps.generation.logic.model_resolver import (  # noqa: PLC0415
        to_pydantic_ai_model,
    )
    from server.apps.generation.logic.stage_model import (  # noqa: PLC0415
        resolve_stage_model,
    )
    from server.apps.pipelines.schemas import (  # noqa: PLC0415
        CandidateRankingOutput,
    )

    model_slug = await resolve_stage_model(ctx, 'footage_search')
    agent: Agent[StageContext, CandidateRankingOutput] = Agent(
        to_pydantic_ai_model(model_slug),
        output_type=CandidateRankingOutput,
        deps_type=StageContext,
    )
    content: list[Any] = [
        (
            f'Scene visual concept: "{visual_concept}". Score each numbered '
            f'image 0.0-1.0 on how well it depicts this concept. Return one '
            f'ranking per image using the external_id given.'
        ),
    ]
    for candidate in candidates:
        content.extend((
            f'external_id={candidate.external_id}',
            ImageUrl(url=candidate.thumb_url),
        ))

    output: CandidateRankingOutput = await llm_client.run_agent(
        agent,
        content,
        ctx,
        stage_key='footage_search',
        model_slug=model_slug,
    )
    scores = {r.external_id: r.score for r in output.rankings}
    return apply_vision_rankings(candidates, output.rankings), scores


@register_stage
class FootageSearchStage(Stage):
    """Documentary stage: find and download one visual per scene."""

    key = 'footage_search'
    queue = 'api'
    max_retries = 3
    timeout_s = 600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by query — one child per scene."""
        queries = ctx.upstream.get('footage_queries', {}).get('queries', [])
        scenes = {
            int(s['idx']): s
            for s in ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        }
        return [
            {
                'scene_idx': q['scene_idx'],
                'primary_query': q['primary_query'],
                'fallback_queries': q.get('fallback_queries', []),
                'media_preference': q.get('media_preference', 'any'),
                'orientation': q.get('orientation', 'landscape'),
                'negative_terms': q.get('negative_terms', []),
                'ai_fallback_prompt': q.get('ai_fallback_prompt', ''),
                'visual_concept': scenes.get(int(q['scene_idx']), {}).get(
                    'visual_concept',
                    '',
                ),
            }
            for q in queries
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Run the cascade for this shard's scene."""
        snap = ctx.execution.input_snapshot
        scene_idx = int(snap['scene_idx'])
        config = ctx.channel.footage_sourcing_or_default()
        provider_names = list(config.enabled_providers)
        if not provider_names:
            from server.apps.channels.models import (  # noqa: PLC0415
                DEFAULT_ENABLED_PROVIDERS,
            )

            provider_names = list(DEFAULT_ENABLED_PROVIDERS)
            logger.warning(
                'footage_providers_empty_using_defaults',
                run_id=str(ctx.run.id),
                scene_idx=scene_idx,
                defaults=provider_names,
            )
        rotated = _rotate_providers(provider_names, scene_idx)
        providers = build_providers(rotated)
        media_type: MediaType = (
            'image' if snap.get('media_preference') == 'image' else 'video'
        )
        logger.info(
            'footage_search_started',
            run_id=str(ctx.run.id),
            scene_idx=scene_idx,
            providers=[p.name for p in providers],
            media_type=media_type,
        )

        queries = [snap['primary_query'], *snap.get('fallback_queries', [])]
        for query in queries:
            candidates = await search_candidates(
                providers=providers,
                query=query,
                media_type=media_type,
                orientation=snap.get('orientation', 'landscape'),
                min_width=config.min_clip_width,
                min_duration_s=config.min_clip_duration_s,
                allowed_licenses=list(config.allowed_licenses),
                limit=config.candidates_per_scene,
            )
            if not candidates:
                continue
            ranked, scores = await self._rank(ctx, candidates, snap, config)
            selected = await self._download_first_usable(
                ctx,
                ranked,
                scene_idx,
                scores,
            )
            if selected is not None:
                return selected

        return await self._ai_fallback(ctx, snap, scene_idx, config)

    async def _rank(
        self,
        ctx: StageContext,
        candidates: list[FootageCandidate],
        snap: dict[str, Any],
        config: Any,
    ) -> tuple[list[FootageCandidate], dict[str, float]]:
        """Order candidates by the channel's configured rerank mode.

        Returns (ranked, scores). ``scores`` is empty for every mode except a
        successful vision pass, so ``rerank_score`` is None whenever no model
        actually scored the pick.
        """
        concept = snap.get('visual_concept', '')
        negatives = snap.get('negative_terms', [])
        if config.rerank_mode == 'none':
            return list(candidates), {}
        if config.rerank_mode == 'vision':
            try:
                return await _vision_rank(ctx, candidates, concept)
            except Exception as exc:
                # Vision re-ranking is an optimisation, never a gate: any
                # model, transport, or validation failure degrades to the
                # metadata heuristic below rather than failing the scene.
                logger.warning(
                    'footage_vision_rerank_failed',
                    run_id=str(ctx.run.id),
                    error=str(exc),
                )
        return rank_by_metadata(
            candidates,
            visual_concept=concept,
            negative_terms=negatives,
        ), {}

    async def _download_first_usable(
        self,
        ctx: StageContext,
        ranked: list[FootageCandidate],
        scene_idx: int,
        scores: dict[str, float],
    ) -> dict[str, Any] | None:
        """Download ranked candidates until one validates; None if all fail."""
        for candidate in ranked:
            downloaded = await _download_and_validate(candidate)
            if downloaded is None:
                continue
            content, mime = downloaded
            suffix = 'mp4' if candidate.media_type == 'video' else 'jpg'
            asset = await ctx.assets.save(
                kind=AssetKind.FOOTAGE,
                content=content,
                filename=f'scene_{scene_idx:04d}.{suffix}',
                mime=mime,
            )
            await _record_credit(
                str(ctx.run.id),
                str(asset.id),
                scene_idx,
                candidate,
            )
            return {
                'scene_idx': scene_idx,
                'asset_id': str(asset.id),
                'media_type': candidate.media_type,
                'source': candidate.provider,
                'license': candidate.license,
                'license_url': candidate.license_url,
                'attribution': candidate.author,
                'attribution_required': candidate.attribution_required,
                'source_url': candidate.source_page_url,
                'rerank_score': scores.get(candidate.external_id),
                'candidates': [_candidate_dict(c) for c in ranked],
            }
        return None

    async def _ai_fallback(
        self,
        ctx: StageContext,
        snap: dict[str, Any],
        scene_idx: int,
        config: Any,
    ) -> dict[str, Any]:
        """Generate the scene with AI, or park when that is disabled."""
        prompt = snap.get('ai_fallback_prompt', '')
        if not config.ai_fallback_enabled or not prompt:
            raise FatalProviderError(
                f'Scene {scene_idx}: no usable footage found and AI '
                f'fallback is unavailable',
                provider='footage_search',
                error_code='no_footage_found',
            )
        used = await _ai_fallback_count(ctx.run)
        if used >= config.max_ai_fallback_per_run:
            raise FatalProviderError(
                f'Scene {scene_idx}: AI-fallback cap of '
                f'{config.max_ai_fallback_per_run} images reached for this '
                f'run',
                provider='footage_search',
                error_code='ai_fallback_cap_exceeded',
            )
        result = await fal_client.generate_image(
            prompt=prompt,
            model=ctx.config.get('ai_model', 'fal-ai/flux/dev'),
            width=1920,
            height=1080,
        )
        content = await _fetch_bytes(result['url'])
        asset = await ctx.assets.save(
            kind=AssetKind.FOOTAGE,
            content=content,
            filename=f'scene_{scene_idx:04d}.jpg',
            mime='image/jpeg',
        )
        await ctx.costs.record(
            provider='fal_flux',
            operation='footage_ai_fallback',
            units=1,
            unit_cost_usd=_AI_IMAGE_COST_USD,
        )
        logger.info(
            'footage_ai_fallback_used',
            run_id=str(ctx.run.id),
            scene_idx=scene_idx,
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'media_type': 'image',
            'source': 'ai_flux',
            'license': 'generated',
            'license_url': '',
            'attribution': '',
            'attribution_required': False,
            'source_url': '',
            'rerank_score': None,
            'candidates': [],
        }


def _candidate_dict(candidate: FootageCandidate) -> dict[str, Any]:
    """Serialise a candidate for the review UI."""
    return {
        'external_id': candidate.external_id,
        'provider': candidate.provider,
        'thumb_url': candidate.thumb_url,
        'preview_url': candidate.download_url,
        'width': candidate.width,
        'height': candidate.height,
        'duration_s': candidate.duration_s,
        'license': candidate.license,
        'author': candidate.author,
        'source_url': candidate.source_page_url,
    }
