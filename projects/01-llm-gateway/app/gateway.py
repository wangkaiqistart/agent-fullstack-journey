"""阶段项目 Gateway 编排：普通调用、流式边界与统一 Trace。"""

import time
from uuid import uuid4

from .config import GatewayConfig
from .providers import ProviderAdapter
from .router import ModelRouter
from .schemas import ChatCompletionRequest, InternalResult
from .usage import UsageStore


class GatewayService:
    def __init__(self, config: GatewayConfig, providers: dict[str, ProviderAdapter], usage: UsageStore):
        self.config = config
        self.router = ModelRouter(config, providers)
        self.usage = usage

    def complete(self, request: ChatCompletionRequest) -> InternalResult:
        started = time.perf_counter()
        trace_id = "trace_" + uuid4().hex[:12]
        candidates = self.router.candidates(request.model, self.config.required_capabilities.get(request.model, {"chat"}))
        last_error = None
        attempts = 0
        for provider in candidates:
            for _ in range(self.config.max_attempts):
                attempts += 1
                try:
                    text, usage, finish_reason = provider.complete(request.messages, max_tokens=request.output_limit)
                    result = InternalResult(
                        text=text,
                        usage=usage,
                        finish_reason=finish_reason,
                        requested_model=request.model,
                        resolved_model=provider.model,
                        provider=provider.name,
                        trace_id=trace_id,
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                        attempts=attempts,
                        fallback_used=provider is not candidates[0],
                    )
                    self.usage.record(result)
                    return result
                except Exception as error:
                    last_error = error
                    if isinstance(error, (TimeoutError, ConnectionError)):
                        continue
                    break
        raise RuntimeError(f"provider_unavailable:{type(last_error).__name__ if last_error else 'none'}")

    def stream(self, request: ChatCompletionRequest):
        candidates = self.router.candidates(request.model, {"chat", "streaming"})
        provider = candidates[0]
        # 此处只选择首个 Provider；流开始后不透明 fallback。
        trace_id = "trace_" + uuid4().hex[:12]
        started = time.perf_counter()
        status = "completed"
        try:
            yield from provider.stream(request.messages, max_tokens=request.output_limit)
        except Exception:
            status = "failed"
            raise
        finally:
            self.usage.record(InternalResult(
                text="",
                requested_model=request.model,
                resolved_model=provider.model,
                provider=provider.name,
                trace_id=trace_id,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                attempts=1,
            ), status=status, error_code=None if status == "completed" else "stream_failed")
