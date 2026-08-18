"""fal.ai provider client — Flux image generation and Kling I2V."""

from typing import Any, NoReturn

import fal_client
from fal_client import FalClientError

from server.common.exceptions import FatalProviderError, RetryableProviderError

_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _raise_fal_error(
    exc: FalClientError,
    provider: str = 'fal',
    fatal_error_code: str | None = None,
) -> NoReturn:
    """Classify a FalClientError and raise the appropriate provider error."""
    status = getattr(exc, 'status', None)
    msg = str(exc)
    if status == 404:
        raise FatalProviderError(
            msg,
            provider=provider,
            error_code='model_not_found',
        ) from exc
    if status in _RETRYABLE_CODES:
        raise RetryableProviderError(
            msg,
            provider=provider,
            status_code=status,
        ) from exc
    if 'safety' in msg.lower() or 'content' in msg.lower():
        raise FatalProviderError(
            msg,
            provider=provider,
            error_code='safety_filter',
        ) from exc
    if fatal_error_code is not None:
        raise FatalProviderError(
            msg,
            provider=provider,
            error_code=fatal_error_code,
        ) from exc
    raise RetryableProviderError(msg, provider=provider) from exc


async def generate_image(
    prompt: str,
    model: str = 'fal-ai/flux/dev',
    negative_prompt: str = '',
    width: int = 1920,
    height: int = 1080,
    seed: int | None = None,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Run a Flux image generation job (async)."""
    arguments = _image_arguments(
        prompt,
        model=model,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        seed=seed,
        image_url=image_url,
        image_urls=image_urls,
    )
    try:
        result = await fal_client.run_async(model, arguments=arguments)
    except FalClientError as exc:
        _raise_fal_error(exc)

    return _parse_image_result(result)


def generate_image_sync(
    prompt: str,
    model: str = 'fal-ai/flux/dev',
    negative_prompt: str = '',
    width: int = 1920,
    height: int = 1080,
    seed: int | None = None,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Run a Flux image generation job (sync).

    Prefer this from sync call sites (Character Studio, auto design).
    ``asyncio.run(generate_image(...))`` binds fal/httpx to a loop that is
    closed on exit, which breaks the next generation in the same worker.
    """
    arguments = _image_arguments(
        prompt,
        model=model,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        seed=seed,
        image_url=image_url,
        image_urls=image_urls,
    )
    try:
        result = fal_client.run(model, arguments=arguments)
    except FalClientError as exc:
        _raise_fal_error(exc)

    return _parse_image_result(result)


def _kontext_arguments(
    prompt: str,
    *,
    seed: int | None,
    image_url: str | None,
    image_urls: list[str] | None,
) -> dict[str, Any]:
    """Build Flux Kontext (single or multi-ref) request args."""
    arguments: dict[str, Any] = {
        'prompt': prompt,
        'num_images': 1,
        'output_format': 'jpeg',
        'aspect_ratio': '16:9',
    }
    if seed is not None:
        arguments['seed'] = seed
    if image_urls:
        arguments['image_urls'] = image_urls
    elif image_url is not None:
        arguments['image_url'] = image_url
    return arguments


def _flux_dev_arguments(
    prompt: str,
    *,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int | None,
    image_url: str | None,
) -> dict[str, Any]:
    """Build fal-ai/flux/dev text-to-image request args."""
    arguments: dict[str, Any] = {
        'prompt': prompt,
        'negative_prompt': negative_prompt,
        'image_size': {'width': width, 'height': height},
        'num_images': 1,
    }
    if seed is not None:
        arguments['seed'] = seed
    if image_url is not None:
        arguments['image_url'] = image_url
    return arguments


def _image_arguments(
    prompt: str,
    *,
    model: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int | None,
    image_url: str | None,
    image_urls: list[str] | None,
) -> dict[str, Any]:
    if 'kontext' in model:
        return _kontext_arguments(
            prompt,
            seed=seed,
            image_url=image_url,
            image_urls=image_urls,
        )
    return _flux_dev_arguments(
        prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        seed=seed,
        image_url=image_url,
    )


def _parse_image_result(result: dict[str, Any]) -> dict[str, Any]:
    images = result.get('images', [])
    if not images:
        raise RetryableProviderError('fal returned no images', provider='fal')

    return {
        'url': images[0]['url'],
        'seed': result.get('seed'),
        'content_policy_violation': result.get('has_nsfw_concepts', [False])[0],
    }


async def generate_video_kling(
    image_url: str,
    prompt: str,
    duration: int = 5,
    model: str = 'fal-ai/kling-video/v2.1/standard/image-to-video',
) -> dict[str, Any]:
    """Run a Kling I2V job. Returns {video_url, duration_s}."""
    try:
        result = await fal_client.run_async(
            model,
            arguments={
                'image_url': image_url,
                'prompt': prompt,
                'duration': str(duration),
            },
        )
    except FalClientError as exc:
        _raise_fal_error(exc, provider='kling', fatal_error_code='kling_error')

    video = result.get('video', {})
    return {'video_url': video.get('url', ''), 'duration_s': duration}
