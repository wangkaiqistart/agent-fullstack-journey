"""OpenAI Compatible Provider；SDK 对象不离开这里。"""

from dataclasses import dataclass
from typing import Iterable

from openai import OpenAI

from .config import ProviderConfig
from .schemas import Message, Usage


@dataclass(frozen=True)
class Chunk:
    delta: str
    finish_reason: str | None = None


class ProviderAdapter:
    def __init__(self, config: ProviderConfig):
        self.name = config.name
        self.model = config.model
        self.capabilities = config.capabilities
        self.client = OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=60.0, max_retries=0)

    def complete(self, messages: list[Message], *, max_tokens: int):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[message.model_dump() for message in messages],
            max_completion_tokens=max_tokens,
        )
        if not response.choices or not response.choices[0].message.content:
            raise RuntimeError("empty_or_incomplete_response")
        choice = response.choices[0]
        usage = response.usage
        return choice.message.content, Usage(
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        ), choice.finish_reason or "stop"

    def stream(self, messages: list[Message], *, max_tokens: int) -> Iterable[Chunk]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[message.model_dump() for message in messages],
            stream=True,
            max_completion_tokens=max_tokens,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            yield Chunk(choice.delta.content or "", choice.finish_reason)
