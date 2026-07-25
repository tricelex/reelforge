"""Smoke tests for generation provider clients (all providers mocked)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_fal_generate_image_retryable_on_429() -> None:
    """FalClientError with status 429 raises RetryableProviderError."""
    from fal_client import FalClientError

    from server.apps.generation.clients.fal import (
        generate_image,
    )
    from server.common.exceptions import RetryableProviderError

    exc = FalClientError('rate limited')
    exc.status = 429

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=exc):
            await generate_image('a lion')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_fal_generate_image_fatal_on_safety() -> None:
    """FalClientError with 'safety' in message raises FatalProviderError."""
    from fal_client import FalClientError

    from server.apps.generation.clients.fal import (
        generate_image,
    )
    from server.common.exceptions import FatalProviderError

    exc = FalClientError('content safety violation')
    exc.status = 400

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=exc):
            await generate_image('prompt')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError:
        pass


def test_fal_generate_image_fatal_on_404() -> None:
    """FalClientError with status 404 raises FatalProviderError (bad model slug)."""
    from fal_client import FalClientError

    from server.apps.generation.clients.fal import (
        generate_image,
    )
    from server.common.exceptions import FatalProviderError

    exc = FalClientError("Application 'flux-kontext-pro' not found")
    exc.status = 404

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=exc):
            await generate_image('prompt', model='fal-ai/flux-kontext-pro')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError as err:
        assert err.error_code == 'model_not_found'


def test_fal_generate_image_retryable_on_no_images() -> None:
    """Empty images list from fal raises RetryableProviderError."""
    from server.apps.generation.clients.fal import (
        generate_image,
    )
    from server.common.exceptions import RetryableProviderError

    async def _inner() -> None:
        with patch(
            'fal_client.run_async',
            new=AsyncMock(return_value={'images': []}),
        ):
            await generate_image('a lion')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_exa_search_retryable_on_500() -> None:
    """Exa 500 response raises RetryableProviderError."""
    import httpx

    from server.apps.generation.clients.search import search
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 500
    mock_resp.text = 'server error'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await search('test query', api_key='test_key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_exa_search_returns_results_on_success() -> None:
    """Successful Exa response returns list of result dicts."""
    import httpx

    from server.apps.generation.clients.search import search

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'results': [
            {
                'url': 'https://example.com',
                'title': 'Rome',
                'text': 'Rome fell.',
            },
        ],
    }

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await search('Rome fell', api_key='key')

    results = asyncio.run(_inner())
    assert len(results) == 1
    assert results[0]['url'] == 'https://example.com'


def test_exa_search_requests_max_characters_in_body() -> None:
    """search() asks Exa to cap page text via maxCharacters."""
    import httpx

    from server.apps.generation.clients.search import search

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.json.return_value = {'results': []}
    captured_body: list[dict[str, object]] = []

    async def _fake_post(
        url: str,
        *,
        headers: object = None,
        json: dict[str, object] | None = None,
    ) -> object:
        captured_body.append(json)
        return mock_resp

    async def _inner() -> list[dict[str, object]]:
        with patch('httpx.AsyncClient.post', side_effect=_fake_post):
            return await search(
                'query',
                api_key='key',
                max_characters_per_result=8000,
            )

    asyncio.run(_inner())
    assert captured_body[0]['contents'] == {'text': {'maxCharacters': 8000}}


def test_exa_search_highlights_mode_uses_query_in_body() -> None:
    """Agent-style search requests query-relevant highlights, not full pages."""
    import httpx

    from server.apps.generation.clients.search import search

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.json.return_value = {'results': []}
    captured_body: list[dict[str, object]] = []

    async def _fake_post(
        url: str,
        *,
        headers: object = None,
        json: dict[str, object] | None = None,
    ) -> object:
        captured_body.append(json)
        return mock_resp

    async def _inner() -> list[dict[str, object]]:
        with patch('httpx.AsyncClient.post', side_effect=_fake_post):
            return await search(
                'fall of rome causes',
                api_key='key',
                content_mode='highlights',
                max_characters_per_result=1500,
            )

    asyncio.run(_inner())
    assert captured_body[0]['contents'] == {
        'highlights': {
            'query': 'fall of rome causes',
            'maxCharacters': 1500,
        },
    }


def test_exa_search_joins_highlights_into_text_field() -> None:
    """Highlight payloads are flattened into the text field for the agent."""
    import httpx

    from server.apps.generation.clients.search import search

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        'results': [
            {
                'url': 'https://example.com',
                'title': 'Rome',
                'highlights': ['Fact one.', 'Fact two.'],
            },
        ],
    }

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await search(
                'rome',
                api_key='key',
                content_mode='highlights',
            )

    results = asyncio.run(_inner())
    assert results[0]['text'] == 'Fact one.\nFact two.'
    """search() truncates oversized page text returned by Exa."""
    import httpx

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        'results': [
            {
                'url': 'https://example.com',
                'title': 'Long page',
                'text': 'x' * 20_000,
            },
        ],
    }

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await search(
                'query',
                api_key='key',
                max_characters_per_result=1000,
                max_total_characters=1000,
            )

    results = asyncio.run(_inner())
    assert len(results[0]['text']) == 1000
    assert results[0]['text'].endswith('...')


def test_elevenlabs_synthesize_returns_bytes_on_success() -> None:
    """Successful ElevenLabs response returns audio bytes."""
    import httpx

    from server.apps.generation.clients.elevenlabs import (
        synthesize,
    )

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.content = b'fake-mp3-data'

    async def _inner() -> bytes:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await synthesize(
                'Hello world',
                voice_id='xyz',
                api_key='key',
            )

    result = asyncio.run(_inner())
    assert result == b'fake-mp3-data'


def test_elevenlabs_synthesize_retryable_on_429() -> None:
    """ElevenLabs 429 raises RetryableProviderError."""
    import httpx

    from server.apps.generation.clients.elevenlabs import (
        synthesize,
    )
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 429
    mock_resp.text = 'rate limited'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await synthesize('text', voice_id='v', api_key='k')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_elevenlabs_synthesize_fatal_on_422() -> None:
    """ElevenLabs 422 raises FatalProviderError."""
    import httpx

    from server.apps.generation.clients.elevenlabs import (
        synthesize,
    )
    from server.common.exceptions import FatalProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 422
    mock_resp.text = 'validation error'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await synthesize('text', voice_id='v', api_key='k')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError:
        pass


def test_elevenlabs_synthesize_retryable_on_unknown_status() -> None:
    """ElevenLabs non-422, non-retryable failure raises RetryableProviderError."""
    import httpx

    from server.apps.generation.clients.elevenlabs import (
        synthesize,
    )
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 400
    mock_resp.text = 'bad request'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await synthesize('text', voice_id='v', api_key='k')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_fal_generate_image_success_returns_dict() -> None:
    """Successful fal.generate_image returns url, seed, content_policy_violation."""
    from server.apps.generation.clients.fal import (
        generate_image,
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'fal_client.run_async',
            new=AsyncMock(
                return_value={
                    'images': [{'url': 'https://fal.ai/img.jpg'}],
                    'seed': 42,
                    'has_nsfw_concepts': [False],
                },
            ),
        ):
            return await generate_image('a lion', seed=42)  # type: ignore[return-value]

    result = asyncio.run(_inner())
    assert result['url'] == 'https://fal.ai/img.jpg'
    assert result['seed'] == 42
    assert result['content_policy_violation'] is False


def test_fal_generate_image_sync_success_returns_dict() -> None:
    """generate_image_sync uses fal_client.run (no event loop)."""
    from server.apps.generation.clients.fal import generate_image_sync

    with patch(
        'fal_client.run',
        return_value={
            'images': [{'url': 'https://cdn.example/x.png'}],
            'seed': 7,
            'has_nsfw_concepts': [False],
        },
    ):
        result = generate_image_sync('a lion', seed=7)
    assert result['url'] == 'https://cdn.example/x.png'
    assert result['seed'] == 7
    assert result['content_policy_violation'] is False


def test_fal_generate_image_with_image_url_arg() -> None:
    """generate_image includes image_url in arguments when provided."""
    from server.apps.generation.clients.fal import (
        generate_image,
    )

    captured: list[dict[str, object]] = []

    async def _fake_run_async(
        model: str,
        *,
        arguments: dict[str, object],
    ) -> object:
        captured.append(arguments)
        return {
            'images': [{'url': 'https://fal.ai/out.jpg'}],
            'seed': 1,
            'has_nsfw_concepts': [False],
        }

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=_fake_run_async):
            await generate_image(
                'img2img prompt',
                image_url='https://src.img/ref.jpg',
            )

    asyncio.run(_inner())
    assert captured[0].get('image_url') == 'https://src.img/ref.jpg'


def test_fal_generate_image_retryable_on_other_fal_error() -> None:
    """FalClientError without retryable status and no safety message → RetryableProviderError."""
    from fal_client import FalClientError

    from server.apps.generation.clients.fal import (
        generate_image,
    )
    from server.common.exceptions import RetryableProviderError

    exc = FalClientError('network timeout')
    exc.status = None  # not a known retryable code

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=exc):
            await generate_image('a lion')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_fal_generate_video_kling_success() -> None:
    """generate_video_kling returns video_url and duration_s on success."""
    from server.apps.generation.clients.fal import (
        generate_video_kling,
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'fal_client.run_async',
            new=AsyncMock(
                return_value={
                    'video': {'url': 'https://fal.ai/vid.mp4'},
                },
            ),
        ):
            return await generate_video_kling(  # type: ignore[return-value]
                image_url='https://src/img.jpg',
                prompt='cinematic motion',
                duration=5,
            )

    result = asyncio.run(_inner())
    assert result['video_url'] == 'https://fal.ai/vid.mp4'
    assert result['duration_s'] == 5


def test_fal_generate_video_kling_retryable_on_429() -> None:
    """Kling FalClientError with status 429 raises RetryableProviderError."""
    from fal_client import FalClientError

    from server.apps.generation.clients.fal import (
        generate_video_kling,
    )
    from server.common.exceptions import RetryableProviderError

    exc = FalClientError('rate limited')
    exc.status = 429

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=exc):
            await generate_video_kling('url', 'prompt')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError:
        pass


def test_fal_generate_video_kling_fatal_on_other_error() -> None:
    """Kling FalClientError without retryable status raises FatalProviderError."""
    from fal_client import FalClientError

    from server.apps.generation.clients.fal import (
        generate_video_kling,
    )
    from server.common.exceptions import FatalProviderError

    exc = FalClientError('model error')
    exc.status = 400  # 400 not in _RETRYABLE_CODES → FatalProviderError

    async def _inner() -> None:
        with patch('fal_client.run_async', side_effect=exc):
            await generate_video_kling('url', 'prompt')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError:
        pass


def test_exa_search_without_contents_flag() -> None:
    """search() with contents=False omits contents key from request body."""
    import httpx

    from server.apps.generation.clients.search import search

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.json.return_value = {'results': []}

    captured_body: list[dict[str, object]] = []

    async def _fake_post(
        url: str,
        *,
        headers: object = None,
        json: dict[str, object] | None = None,
    ) -> object:
        captured_body.append(json)
        return mock_resp

    async def _inner() -> list[dict[str, object]]:
        with patch('httpx.AsyncClient.post', side_effect=_fake_post):
            return await search('query', api_key='key', contents=False)

    result = asyncio.run(_inner())
    assert result == []
    assert 'contents' not in captured_body[0]


def test_elevenlabs_force_align_returns_words_on_success() -> None:
    """Successful Forced Alignment response returns word timings."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import force_align

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'words': [
            {'text': 'hello', 'start': 0.0, 'end': 0.4, 'loss': 0.1},
            {'text': 'world', 'start': 0.4, 'end': 0.9, 'loss': 0.05},
        ],
        'characters': [],
        'loss': 0.075,
    }

    async def _inner() -> dict:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            return await force_align(
                Path('/tmp/audio.mp3'),
                'hello world',
                'test-key',
            )

    result = asyncio.run(_inner())
    assert len(result['words']) == 2
    assert result['words'][0]['text'] == 'hello'
    assert result['loss'] == 0.075


def test_elevenlabs_force_align_retryable_on_429() -> None:
    """Forced Alignment 429 raises RetryableProviderError."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import force_align
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 429
    mock_resp.text = 'rate limited'

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            await force_align(Path('/tmp/audio.mp3'), 'hello', 'test-key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError as exc:
        assert exc.provider == 'elevenlabs'


def test_elevenlabs_force_align_retryable_on_unknown_status() -> None:
    """Forced Alignment non-422 failure raises RetryableProviderError."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import force_align
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 400
    mock_resp.text = 'bad request'

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            await force_align(Path('/tmp/audio.mp3'), 'hello', 'test-key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError as exc:
        assert exc.provider == 'elevenlabs'


def test_elevenlabs_force_align_fatal_on_422() -> None:
    """Forced Alignment 422 raises FatalProviderError."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import force_align
    from server.common.exceptions import FatalProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 422
    mock_resp.text = 'validation error'

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            await force_align(Path('/tmp/audio.mp3'), 'hello', 'test-key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError as exc:
        assert exc.provider == 'elevenlabs'


def test_elevenlabs_calculate_transcription_cost() -> None:
    from decimal import Decimal

    from server.apps.generation.clients.elevenlabs import (
        calculate_transcription_cost,
    )

    assert calculate_transcription_cost(60.0) == Decimal('0.003670')
    assert calculate_transcription_cost(0.0) == Decimal('0.000000')


def test_elevenlabs_transcribe_returns_words_on_success() -> None:
    """Successful ElevenLabs Scribe response returns diarized transcript JSON."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import transcribe

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'text': 'hello world',
        'words': [
            {
                'text': 'hello',
                'start': 0.0,
                'end': 0.5,
                'type': 'word',
                'speaker_id': 'speaker_0',
            },
        ],
        'audio_duration_secs': 1.5,
    }

    async def _inner() -> dict:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            return await transcribe(Path('/tmp/audio.mp3'), 'test-key')

    result = asyncio.run(_inner())
    assert result['text'] == 'hello world'
    assert result['audio_duration_secs'] == 1.5
    assert result['words'][0]['speaker_id'] == 'speaker_0'


def test_elevenlabs_transcribe_retryable_on_429() -> None:
    """ElevenLabs Scribe 429 raises RetryableProviderError."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import transcribe
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 429
    mock_resp.text = 'rate limited'

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            await transcribe(Path('/tmp/audio.mp3'), 'test-key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError as exc:
        assert exc.provider == 'elevenlabs'


def test_elevenlabs_transcribe_retryable_on_unknown_status() -> None:
    """ElevenLabs Scribe non-422, non-retryable failure raises RetryableProviderError."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import transcribe
    from server.common.exceptions import RetryableProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 400
    mock_resp.text = 'bad request'

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            await transcribe(Path('/tmp/audio.mp3'), 'test-key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError as exc:
        assert exc.provider == 'elevenlabs'


def test_elevenlabs_transcribe_fatal_on_422() -> None:
    """ElevenLabs Scribe 422 raises FatalProviderError."""
    from pathlib import Path

    import httpx

    from server.apps.generation.clients.elevenlabs import transcribe
    from server.common.exceptions import FatalProviderError

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 422
    mock_resp.text = 'validation error'

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.post',
                new=AsyncMock(return_value=mock_resp),
            ),
            patch('pathlib.Path.open', create=True),
        ):
            await transcribe(Path('/tmp/audio.mp3'), 'test-key')

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError as exc:
        assert exc.provider == 'elevenlabs'


def test_run_agent_skips_cost_recording_when_zero_tokens() -> None:
    """run_agent() skips ctx.costs.record when token counts are zero."""
    from server.apps.generation.clients.llm import run_agent

    mock_usage = MagicMock()
    mock_usage.input_tokens = 0
    mock_usage.output_tokens = 0

    mock_result = MagicMock()
    mock_result.usage = mock_usage
    mock_result.output = 'done'

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.costs.record = AsyncMock()

    async def _inner() -> object:
        return await run_agent(mock_agent, 'prompt', mock_ctx, stage_key='test')

    result = asyncio.run(_inner())
    assert result == 'done'
    mock_ctx.costs.record.assert_not_called()


def test_run_agent_records_input_and_output_token_costs() -> None:
    """run_agent() calls ctx.costs.record for input and output tokens."""
    from unittest.mock import MagicMock

    from server.apps.generation.clients.llm import run_agent

    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    mock_result = MagicMock()
    mock_result.usage = mock_usage
    mock_result.output = {'title': 'Rome'}

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.costs.record = AsyncMock()

    async def _inner() -> object:
        return await run_agent(
            mock_agent,
            'user prompt',
            mock_ctx,
            stage_key='metadata',
        )

    result = asyncio.run(_inner())
    assert result == {'title': 'Rome'}
    assert mock_ctx.costs.record.await_count == 2
    calls = [c.kwargs for c in mock_ctx.costs.record.await_args_list]
    operations = [c['operation'] for c in calls]
    assert any('input' in op for op in operations)
    assert any('output' in op for op in operations)


def test_run_agent_passes_input_token_limit_to_usage_limits() -> None:
    """run_agent() forwards input_tokens_limit to pydantic-ai UsageLimits."""
    from pydantic_ai.usage import UsageLimits

    from server.apps.generation.clients.llm import run_agent

    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 5

    mock_result = MagicMock()
    mock_result.usage = mock_usage
    mock_result.output = 'done'

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.costs.record = AsyncMock()

    async def _inner() -> object:
        return await run_agent(
            mock_agent,
            'prompt',
            mock_ctx,
            stage_key='research',
            input_tokens_limit=250_000,
            count_tokens_before_request=True,
        )

    asyncio.run(_inner())
    limits = mock_agent.run.await_args.kwargs['usage_limits']
    assert isinstance(limits, UsageLimits)
    assert limits.input_tokens_limit == 250_000
    assert limits.count_tokens_before_request is True


def test_run_agent_passes_default_max_tokens_model_settings() -> None:
    """run_agent() sets max_tokens so Anthropic does not use 4096 default."""
    from server.apps.generation.clients.llm import run_agent

    mock_usage = MagicMock()
    mock_usage.input_tokens = 0
    mock_usage.output_tokens = 0
    mock_result = MagicMock()
    mock_result.usage = mock_usage
    mock_result.output = 'done'
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)
    mock_ctx = MagicMock()
    mock_ctx.costs.record = AsyncMock()
    # Non-dict MagicMock settings must be ignored.
    mock_ctx.prompts.get_generation_settings = MagicMock(return_value=None)

    async def _inner() -> object:
        return await run_agent(mock_agent, 'prompt', mock_ctx, stage_key='script')

    asyncio.run(_inner())
    settings = mock_agent.run.await_args.kwargs['model_settings']
    assert settings['max_tokens'] == 8192


def test_run_agent_uses_prompt_generation_settings() -> None:
    """run_agent() prefers PromptRenderer generation settings when present."""
    from server.apps.generation.clients.llm import run_agent

    mock_usage = MagicMock()
    mock_usage.input_tokens = 0
    mock_usage.output_tokens = 0
    mock_result = MagicMock()
    mock_result.usage = mock_usage
    mock_result.output = 'done'
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)
    mock_ctx = MagicMock()
    mock_ctx.costs.record = AsyncMock()
    mock_ctx.prompts.get_generation_settings = AsyncMock(
        return_value={'max_tokens': 16384, 'temperature': 0.4},
    )

    async def _inner() -> object:
        return await run_agent(
            mock_agent,
            'prompt',
            mock_ctx,
            stage_key='script',
        )

    asyncio.run(_inner())
    settings = mock_agent.run.await_args.kwargs['model_settings']
    assert settings['max_tokens'] == 16384
    assert settings['temperature'] == 0.4


def test_run_agent_wraps_unexpected_model_behavior_as_retryable() -> None:
    """UnexpectedModelBehavior becomes RetryableProviderError for stage retries."""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from server.apps.generation.clients.llm import run_agent
    from server.common.exceptions import RetryableProviderError

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(
        side_effect=UnexpectedModelBehavior(
            'Exceeded maximum output retries (1)',
        ),
    )
    mock_ctx = MagicMock()
    mock_ctx.costs.record = AsyncMock()
    mock_ctx.prompts.get_generation_settings = AsyncMock(
        return_value={'max_tokens': 8192, 'temperature': 1.0},
    )

    async def _inner() -> None:
        await run_agent(
            mock_agent,
            'prompt',
            mock_ctx,
            stage_key='script',
            model_slug='claude-opus-4-8',
        )

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RetryableProviderError')
    except RetryableProviderError as exc:
        assert 'Exceeded maximum output retries' in str(exc)
        assert exc.provider == 'anthropic'
