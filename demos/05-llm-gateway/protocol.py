"""Gateway 对外协议；Provider SDK 对象不能越过这一层。"""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: str = Field(default="default", min_length=1, max_length=80)
    messages: list[Message] = Field(min_length=1, max_length=100)
    prompt_template: str | None = None
    prompt_version: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    schema_name: Literal["agent_decision"] | None = None
    max_output_tokens: int = Field(default=512, ge=1, le=4096)


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LLMResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: "req_" + uuid4().hex[:12])
    trace_id: str
    model: str
    provider: str
    output_text: str
    usage: Usage = Field(default_factory=Usage)
    attempts: int = 1
    fallback_used: bool = False
    latency_ms: float
    status: Literal["completed"] = "completed"


class TraceRecord(BaseModel):
    trace_id: str
    request_id: str
    model: str
    provider: str
    prompt_template: str | None
    prompt_version: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost: float | None
    latency_ms: float
    attempts: int
    status: str
    error_code: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def new_trace_id() -> str:
    return "trace_" + uuid4().hex[:12]
