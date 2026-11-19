"""把两种 API 的 SDK 响应转换为统一结果，让业务层无需识别嵌套字段。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelResult:
    text: str
    finish_reason: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


class ChatModel(Protocol):
    def generate(self, messages, *, max_tokens=1024, schema=None) -> ModelResult: ...


class ChatCompletionsAdapter:
    def __init__(self, client, model):
        self.client = client
        self.model = model

    def generate(self, messages, *, max_tokens=1024, schema=None):
        options = {}
        if schema is not None:
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "patch_plan", "strict": True, "schema": schema},
            }
        response = self.client.chat.completions.create(
            model=self.model, messages=messages,
            max_completion_tokens=max_tokens, **options,
        )
        if not response.choices:
            raise ValueError("Chat 响应中没有 choices")
        choice = response.choices[0]
        if choice.message.refusal:
            raise ValueError("模型拒答")
        if choice.finish_reason != "stop" or not choice.message.content:
            raise ValueError(f"Chat 文本未正常完成：{choice.finish_reason}")
        usage = response.usage
        return ModelResult(
            choice.message.content, "stop", response.model,
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
        )


class ResponsesAdapter:
    def __init__(self, client, model):
        self.client = client
        self.model = model

    def generate(self, messages, *, max_tokens=1024, schema=None):
        options = {}
        if schema is not None:
            options["text"] = {
                "format": {"type": "json_schema", "name": "patch_plan", "strict": True, "schema": schema},
            }
        response = self.client.responses.create(
            model=self.model, input=messages, max_output_tokens=max_tokens,
            store=False, **options,
        )
        if response.status != "completed":
            raise ValueError(f"Responses 未完成：{response.status}")
        for item in response.output:
            if item.type == "function_call":
                raise ValueError("此文本 Adapter 不执行工具，请运行工具示例")
            if item.type == "message" and any(part.type == "refusal" for part in item.content):
                raise ValueError("模型拒答")
        if not response.output_text:
            raise ValueError("Responses 没有文本")
        usage = response.usage
        # 只有完整文本才映射为 stop；不会把工具请求当作任务完成。
        return ModelResult(
            response.output_text, "stop", response.model,
            usage.input_tokens if usage else None,
            usage.output_tokens if usage else None,
        )
