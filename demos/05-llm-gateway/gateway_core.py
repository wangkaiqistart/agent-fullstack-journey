"""Gateway 核心：协议、模板、Provider、有限重试和 Trace。"""

import time
from collections.abc import Callable, Iterable

from protocol import ChatRequest, LLMResponse, TraceRecord, Usage, new_trace_id
from prompt_store import render_template
from provider import Provider, ProviderResult


TRANSIENT_ERRORS = (TimeoutError, ConnectionError)


class GatewayError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}:{message}")


class Gateway:
    def __init__(self, providers: dict[str, Provider], *, trace_sink: Callable[[TraceRecord], None] | None = None):
        self.providers = providers
        self.trace_sink = trace_sink or (lambda _record: None)

    def _messages(self, request: ChatRequest) -> list[dict]:
        messages = [message.model_dump() for message in request.messages]
        if request.prompt_template:
            try:
                template = render_template(request.prompt_template, request.prompt_version, request.variables)
                messages.insert(0, {"role": "system", "content": template.render(request.variables)})
            except ValueError as error:
                code, _, detail = str(error).partition(":")
                raise GatewayError(code, detail or code) from None
        return messages

    @staticmethod
    def _check_schema(request: ChatRequest, result: ProviderResult):
        if request.schema_name != "agent_decision":
            return
        # 这里用结构化输出 Demo 的本地协议作为示例出口校验。
        from gateway_schema import validate_agent_decision

        try:
            validate_agent_decision(result.text)
        except Exception as error:
            raise GatewayError("schema_validation_failed", str(error)) from None

    def complete(self, request: ChatRequest) -> LLMResponse:
        trace_id = new_trace_id()
        started = time.perf_counter()
        messages = self._messages(request)
        provider_names = [request.model] if request.model != "default" else ["primary", "backup"]
        attempts = 0
        last_error: Exception | None = None
        for provider_name in provider_names:
            provider = self.providers.get(provider_name)
            if provider is None:
                if provider_name == "backup":
                    continue
                raise GatewayError("unknown_model", request.model)
            for retry_index in range(2):
                attempts += 1
                try:
                    result = provider.complete(messages, max_output_tokens=request.max_output_tokens)
                    self._check_schema(request, result)
                    latency = (time.perf_counter() - started) * 1000
                    response = LLMResponse(
                        trace_id=trace_id,
                        model=request.model,
                        provider=provider_name,
                        output_text=result.text,
                        usage=Usage(
                            input_tokens=result.usage.input_tokens,
                            output_tokens=result.usage.output_tokens,
                            total_tokens=result.usage.total_tokens,
                        ),
                        attempts=attempts,
                        fallback_used=provider_name == "backup",
                        latency_ms=round(latency, 2),
                    )
                    self._trace(request, response, None)
                    return response
                except GatewayError as error:
                    self._trace_error(request, trace_id, attempts, started, error)
                    raise
                except TRANSIENT_ERRORS as error:
                    last_error = error
                    if retry_index == 0:
                        continue
                    break
                except Exception as error:
                    last_error = error
                    break
        self._trace_error(request, trace_id, attempts, started, last_error)
        raise GatewayError("provider_unavailable", type(last_error).__name__ if last_error else "no_provider")

    def stream(self, request: ChatRequest) -> Iterable[dict]:
        """首个 delta 发出后不切换 Provider，避免拼接两次答案。"""
        trace_id = new_trace_id()
        started = time.perf_counter()
        messages = self._messages(request)
        provider_name = "primary" if request.model == "default" else request.model
        provider = self.providers.get(provider_name)
        if provider is None:
            raise GatewayError("unknown_model", request.model)
        try:
            for chunk in provider.stream(messages, max_output_tokens=request.max_output_tokens):
                if chunk.delta:
                    yield {"type": "content.delta", "data": {"delta": chunk.delta}}
                if chunk.finish_reason:
                    yield {"type": "response.completed", "data": {"finish_reason": chunk.finish_reason}}
            self.trace_sink(TraceRecord(
                trace_id=trace_id,
                request_id="stream_" + trace_id.removeprefix("trace_"),
                model=request.model,
                provider=provider_name,
                prompt_template=request.prompt_template,
                prompt_version=request.prompt_version,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                cost=None,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                attempts=1,
                status="completed",
            ))
        except Exception as error:
            self.trace_sink(TraceRecord(
                trace_id=trace_id,
                request_id="stream_" + trace_id.removeprefix("trace_"),
                model=request.model,
                provider=provider_name,
                prompt_template=request.prompt_template,
                prompt_version=request.prompt_version,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                cost=None,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                attempts=1,
                status="failed",
                error_code=type(error).__name__,
            ))
            # 流开始后只能发送失败事件，不能静默切换模型重写。
            yield {"type": "response.failed", "data": {"code": "stream_failed"}}

    def _trace(self, request: ChatRequest, response: LLMResponse, error_code: str | None):
        self.trace_sink(TraceRecord(
            trace_id=response.trace_id,
            request_id=response.request_id,
            model=response.model,
            provider=response.provider,
            prompt_template=request.prompt_template,
            prompt_version=request.prompt_version,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            cost=None,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            status=response.status,
            error_code=error_code,
        ))

    def _trace_error(self, request: ChatRequest, trace_id: str, attempts: int, started: float, error: Exception | None):
        self.trace_sink(TraceRecord(
            trace_id=trace_id,
            request_id="unknown",
            model=request.model,
            provider="unknown",
            prompt_template=request.prompt_template,
            prompt_version=request.prompt_version,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            cost=None,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            attempts=attempts,
            status="failed",
            error_code=getattr(error, "code", None) or (type(error).__name__ if error else "no_provider"),
        ))
