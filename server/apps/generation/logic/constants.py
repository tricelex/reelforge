"""Shared LLM provider and model identifiers."""

DEFAULT_LLM_MODEL = 'gpt-5.6-terra'
DEFAULT_LLM_PROVIDER = 'openai'
# Use the OpenAI Responses API (recommended for tool-using agents). The bare
# 'openai:' prefix is deprecated and will default to Responses in pydantic-ai
# v2; 'openai-chat:' selects legacy Chat Completions instead.
PYDANTIC_AI_MODEL = f'openai-responses:{DEFAULT_LLM_MODEL}'
