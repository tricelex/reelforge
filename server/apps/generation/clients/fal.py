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
    if status in _RETRYABLE_CODES:
        raise RetryableProviderError(
            msg, provider=provider, status_code=status,
        ) from exc
    if 'safety' in msg.lower() or 'content' in msg.lower():
        raise FatalProviderError(
            msg, provider=provider, error_code='safety_filter',
        ) from exc
    if fatal_error_code is not None:
        raise FatalProviderError(
            msg, provider=provider, error_code=fatal_error_code,
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
) -> dict[str, Any]:
    """Run a Flux image generation job."""
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

    try:
        result = await fal_client.run_async(model, arguments=arguments)
    except FalClientError as exc:
        _raise_fal_error(exc)

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
