"""Text embeddings client — used for cross-run script similarity detection."""

from openai import AsyncOpenAI

_EMBEDDING_MODEL = 'text-embedding-3-small'
_MAX_CHARS = 8000


async def embed_text(text: str) -> list[float]:
    """Return a text-embedding-3-small vector for the given text."""
    client = AsyncOpenAI()
    response = await client.embeddings.create(
        model=_EMBEDDING_MODEL,
        input=text[:_MAX_CHARS],
    )
    return list(response.data[0].embedding)
