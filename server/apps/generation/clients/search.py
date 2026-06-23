"""Exa web search client for the research stage."""

from typing import Any

import httpx

from server.common.exceptions import RetryableProviderError

_BASE = 'https://api.exa.ai'


async def search(
    query: str,
    api_key: str,
    num_results: int = 8,
    *,
    use_autoprompt: bool = True,
    contents: bool = True,
) -> list[dict[str, Any]]:
    """Search Exa and return list of {url, title, text} results."""
    body: dict[str, Any] = {
        'query': query,
        'numResults': num_results,
        'useAutoprompt': use_autoprompt,
    }
    if contents:
        body['contents'] = {'text': True}

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
    return [
        {
            'url': r.get('url', ''),
            'title': r.get('title', ''),
            'text': r.get('text', ''),
        }
        for r in data.get('results', [])
    ]
