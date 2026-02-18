import anthropic

from reelforge.services.base import BaseLLMProvider
from reelforge.services.dataclass import LLMResponse

CLAUDE_PRICING = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},  # per 1M tokens
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25},
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
}


class ClaudeProvider(BaseLLMProvider):
    name = "claude"

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-5") -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
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
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "You are an expert YouTube content strategist.",
            messages=[{"role": "user", "content": prompt}],
        )
        pricing = CLAUDE_PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost = (
            response.usage.input_tokens / 1e6 * pricing["input"]
            + response.usage.output_tokens / 1e6 * pricing["output"]
        )
        return LLMResponse(
            text=response.content[0].text,
            model=model,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
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
