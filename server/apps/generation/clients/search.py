"""Exa web search client for the research stage."""

from typing import Any, Literal

import httpx

from server.common.exceptions import RetryableProviderError

_BASE = 'https://api.exa.ai'

# Defaults for direct programmatic use (tests, one-off calls).
_DEFAULT_NUM_RESULTS = 8
_DEFAULT_MAX_CHARACTERS_PER_RESULT = 8_000
_DEFAULT_MAX_TOTAL_CHARACTERS = 56_000

# Tighter budget for pydantic-ai tool loops: every prior web_search stays in
# the model context for the rest of the run (triangular growth across rounds).
AGENT_NUM_RESULTS = 5
AGENT_MAX_CHARACTERS_PER_RESULT = 1_500
AGENT_MAX_TOTAL_CHARACTERS = 7_500


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ''
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f'{text[: max_chars - 3]}...'


def _result_text(result: dict[str, Any]) -> str:
    text = str(result.get('text', '') or '')
    if text:
        return text
    highlights = result.get('highlights')
    if isinstance(highlights, list):
        return '\n'.join(str(item) for item in highlights if item)
    return ''


def _normalize_results(
    results: list[dict[str, Any]],
    *,
    max_characters_per_result: int,
    max_total_characters: int,
) -> list[dict[str, Any]]:
    per_result = min(
        max_characters_per_result,
        max_total_characters // max(len(results), 1),
    )
    return [
        {
            'url': r.get('url', ''),
            'title': r.get('title', ''),
            'text': _truncate_text(_result_text(r), per_result),
        }
        for r in results
    ]


def _build_contents_body(
    *,
    query: str,
    contents: bool,
    content_mode: Literal['text', 'highlights'],
    max_characters_per_result: int,
) -> dict[str, Any] | None:
    if not contents:
        return None
    if content_mode == 'highlights':
        return {
            'highlights': {
                'query': query,
                'maxCharacters': max_characters_per_result,
            },
        }
    return {'text': {'maxCharacters': max_characters_per_result}}


async def search(
    query: str,
    api_key: str,
    num_results: int = _DEFAULT_NUM_RESULTS,
    *,
    use_autoprompt: bool = True,
    contents: bool = True,
    content_mode: Literal['text', 'highlights'] = 'text',
    max_characters_per_result: int = _DEFAULT_MAX_CHARACTERS_PER_RESULT,
    max_total_characters: int = _DEFAULT_MAX_TOTAL_CHARACTERS,
) -> list[dict[str, Any]]:
    """Search Exa and return list of {url, title, text} results."""
    body: dict[str, Any] = {
        'query': query,
        'numResults': num_results,
        'useAutoprompt': use_autoprompt,
    }
    contents_body = _build_contents_body(
        query=query,
        contents=contents,
        content_mode=content_mode,
        max_characters_per_result=max_characters_per_result,
    )
    if contents_body is not None:
        body['contents'] = contents_body

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f'{_BASE}/search',
            headers={
                'x-api-key': api_key,
                'Content-Type': 'application/json',
            },
            json=body,
        )

    if not resp.is_success:
        raise RetryableProviderError(
            f'Exa {resp.status_code}: {resp.text[:200]}',
            provider='exa',
            status_code=resp.status_code,
        )

    data = resp.json()
    return _normalize_results(
        data.get('results', []),
        max_characters_per_result=max_characters_per_result,
        max_total_characters=max_total_characters,
    )
