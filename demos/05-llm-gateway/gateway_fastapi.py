"""FastAPI LLM Gateway：POST /chat、POST /stream、GET /trace。"""

from collections.abc import Iterable

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from gateway_core import Gateway, GatewayError
from protocol import ChatRequest, TraceRecord
from provider import OpenAICompatibleProvider
from settings import load_settings
from sse import encode_event


traces: list[TraceRecord] = []
settings = load_settings()
providers = {name: OpenAICompatibleProvider(config) for name, config in settings.items()}
gateway = Gateway(providers, trace_sink=traces.append)
app = FastAPI(title="Learning LLM Gateway")


@app.post("/chat")
def chat(request: ChatRequest):
    try:
        return gateway.complete(request)
    except GatewayError as error:
        raise HTTPException(status_code=400, detail={"code": error.code, "message": str(error)}) from None


@app.post("/stream")
def stream(request: ChatRequest):
    try:
        events = gateway.stream(request)
    except GatewayError as error:
        raise HTTPException(status_code=400, detail={"code": error.code, "message": str(error)}) from None
    return StreamingResponse((encode_event(event) for event in events), media_type="text/event-stream")


@app.get("/trace")
def trace(trace_id: str | None = None):
    if trace_id:
        matched = [item for item in traces if item.trace_id == trace_id]
        if not matched:
            raise HTTPException(status_code=404, detail={"code": "trace_not_found"})
        return matched[0]
    return traces[-50:]
