from __future__ import annotations

from openai import OpenAI

from reelforge.services.base import BaseLLMProvider
from reelforge.services.dataclass import LLMResponse

OPENAI_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},  # per 1M tokens
    "gpt-4o-mini": {"input": 0.150, "output": 0.600},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "gpt-5.2": {"input": 0.50, "output": 1.50},
}

# Models that use max_completion_tokens instead of max_tokens
_MAX_COMPLETION_TOKENS_MODELS = ("o1", "o3", "gpt-5")


class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def __init__(self, api_key: str, default_model: str = "gpt-5.2") -> None:
        self.client = OpenAI(api_key=api_key)
        self.default_model = default_model

    def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        model = model or self.default_model

        messages = []
        if system:
            messages.append({"role": "system", "content": system or "You are an expert YouTube content strategist."})
        messages.append({"role": "user", "content": prompt})

        uses_max_completion_tokens = any(
            model.startswith(prefix) for prefix in _MAX_COMPLETION_TOKENS_MODELS
        )
        token_kwarg = (
            {"max_completion_tokens": max_tokens}
            if uses_max_completion_tokens
            else {"max_tokens": max_tokens}
        )

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **token_kwarg,
            **kwargs,
        )

        pricing = OPENAI_PRICING.get(model, {"input": 2.50, "output": 10.0})
        cost = (
            response.usage.prompt_tokens / 1e6 * pricing["input"]
            + response.usage.completion_tokens / 1e6 * pricing["output"]
        )

        return LLMResponse(
            text=response.choices[0].message.content,
            model=model,
            tokens_input=response.usage.prompt_tokens,
            tokens_output=response.usage.completion_tokens,
            cost_usd=cost,
            raw=response,
        )

    def complete_json(self, prompt: str, system: str = "", **kwargs) -> dict:
        import json
        import re

        response = self.complete(prompt, system=system, **kwargs)
        text = response.text.strip()
        match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(text)
