"""Shared LLM provider and model identifiers."""

DEFAULT_LLM_MODEL = 'gpt-5.2'
DEFAULT_LLM_PROVIDER = 'openai'
# pydantic-ai needs the explicit 'openai-chat:' prefix to select the Chat
# Completions API. A bare 'openai:' prefix now emits a deprecation warning
# (it will switch to the Responses API in pydantic-ai v2.0), which the test
# suite promotes to an error via ``filterwarnings = ['error']``. The provider
# identifier above stays 'openai' for cost tracking.
PYDANTIC_AI_MODEL = f'openai-chat:{DEFAULT_LLM_MODEL}'
