"""Provider Adapter：SDK 对象在这里结束，Gateway 只消费普通结果。"""

from dataclasses import dataclass
from typing import Iterable, Protocol

from openai import OpenAI

from settings import ProviderConfig


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult:
    text: str
    usage: ProviderUsage
    finish_reason: str | None


@dataclass(frozen=True)
class ProviderChunk:
    delta: str
    finish_reason: str | None = None


class Provider(Protocol):
    name: str

    def complete(self, messages: list[dict], *, max_output_tokens: int) -> ProviderResult: ...

    def stream(self, messages: list[dict], *, max_output_tokens: int) -> Iterable[ProviderChunk]: ...


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig):
        self.name = config.name
        self.model = config.model
        self.client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=60.0,
            max_retries=0,  # 重试由 Gateway 统一控制。
        )

    def complete(self, messages: list[dict], *, max_output_tokens: int) -> ProviderResult:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max_output_tokens,
        )
        if not response.choices:
            raise RuntimeError("empty_choices")
        choice = response.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            raise RuntimeError("incomplete_response")
        usage = response.usage
        return ProviderResult(
            choice.message.content,
            ProviderUsage(
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                getattr(usage, "total_tokens", None),
            ),
            choice.finish_reason,
        )

    def stream(self, messages: list[dict], *, max_output_tokens: int) -> Iterable[ProviderChunk]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            max_completion_tokens=max_output_tokens,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            yield ProviderChunk(choice.delta.content or "", choice.finish_reason)
