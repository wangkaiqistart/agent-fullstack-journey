"""OpenAI Compatible 外部协议与内部标准结果。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    model: str = Field(min_length=1, max_length=80)
    messages: list[Message] = Field(min_length=1, max_length=100)
    stream: bool = False
    max_tokens: int | None = Field(default=None, ge=1, le=4096)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=4096)
    response_format: dict[str, Any] | None = None

    @property
    def output_limit(self) -> int:
        return self.max_completion_tokens or self.max_tokens or 512


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class InternalResult(BaseModel):
    text: str
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str = "stop"
    requested_model: str
    resolved_model: str
    provider: str
    trace_id: str
    latency_ms: float
    attempts: int
    fallback_used: bool = False
