"""阶段一 OpenAI Compatible API。"""

import json
import os
from pathlib import Path
from time import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import load_config
from .gateway import GatewayService
from .providers import ProviderAdapter
from .schemas import ChatCompletionRequest
from .usage import UsageStore


CONFIG_PATH = os.environ.get("GATEWAY_CONFIG", str(Path(__file__).parents[1] / "gateway.example.yaml"))
config = load_config(CONFIG_PATH)
providers = {name: ProviderAdapter(item) for name, item in config.providers.items()}
usage = UsageStore(os.environ.get("GATEWAY_USAGE_DB", "gateway_usage.sqlite3"))
service = GatewayService(config, providers, usage)
app = FastAPI(title="Stage 1 LLM Gateway")
gateway_key = os.environ.get("GATEWAY_API_KEY", "").strip()


def authorized(authorization: str | None):
    if gateway_key and authorization != f"Bearer {gateway_key}":
        raise HTTPException(status_code=401, detail={"code": "unauthorized"})


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if not providers:
        return JSONResponse(status_code=503, content={"status": "not_ready", "code": "no_provider"})
    return {"status": "ready", "providers": sorted(providers)}


@app.get("/admin/providers")
def provider_admin(authorization: str | None = Header(default=None)):
    authorized(authorization)
    return {
        name: {"model": provider.model, "capabilities": sorted(provider.capabilities)}
        for name, provider in providers.items()
    }


@app.post("/v1/chat/completions")
def chat(request: ChatCompletionRequest, authorization: str | None = Header(default=None)):
    authorized(authorization)
    if request.stream:
        def body():
            try:
                for chunk in service.stream(request):
                    payload = {
                        "id": "chatcmpl-stage1",
                        "object": "chat.completion.chunk",
                        "created": int(time()),
                        "model": request.model,
                        "choices": [{"index": 0, "delta": {"content": chunk.delta}, "finish_reason": chunk.finish_reason}],
                    }
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                yield "data: " + json.dumps({"error": {"code": "stream_failed"}}) + "\n\n"
        return StreamingResponse(body(), media_type="text/event-stream")
    try:
        result = service.complete(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"code": str(error).split(":", 1)[0]}) from None
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail={"code": str(error).split(":", 1)[0]}) from None
    return {
        "id": "chatcmpl-stage1",
        "object": "chat.completion",
        "created": int(time()),
        "model": result.requested_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result.text}, "finish_reason": result.finish_reason}],
        "usage": result.usage.model_dump(),
        "x_gateway": {"resolved_model": result.resolved_model, "provider": result.provider, "trace_id": result.trace_id, "attempts": result.attempts},
    }


@app.get("/admin/usage")
def admin_usage(authorization: str | None = Header(default=None)):
    authorized(authorization)
    return usage.recent()
