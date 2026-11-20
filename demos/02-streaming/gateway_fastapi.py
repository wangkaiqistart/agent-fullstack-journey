"""可选 FastAPI Gateway：POST 创建、GET 订阅、POST 取消三个职责分离。"""

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_loop import run_agent
from run_store import InMemoryRunStore
from settings_stream import create_async_client
from sse_codec import encode_heartbeat, encode_sse
from stream_model import OpenAIChatStreamingAdapter

store = InMemoryRunStore()
client = None
model_name = None


class RunRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@asynccontextmanager
async def lifespan(_app):
    global client, model_name
    client, model_name = create_async_client()
    yield
    await client.close()


app = FastAPI(lifespan=lifespan)


@app.post("/runs", status_code=202)
async def create_run(request: RunRequest):
    run_id = store.create()
    adapter = OpenAIChatStreamingAdapter(client, model_name)
    asyncio.create_task(run_agent(
        adapter,
        [{"role": "user", "content": request.question}],
        store,
        run_id=run_id,
    ))
    return {"run_id": run_id, "status": "accepted"}


@app.get("/runs/{run_id}/events")
async def subscribe(
    run_id: str,
    last_event_id: int = -1,
    last_event_id_header: int | None = Header(default=None, alias="Last-Event-ID"),
):
    try:
        store.get(run_id)
    except KeyError:
        raise HTTPException(404, "run 不存在") from None

    async def body():
        # 浏览器 EventSource 使用 Last-Event-ID；命令行也可用查询参数演示。
        cursor = last_event_id_header if last_event_id_header is not None else last_event_id
        idle_rounds = 0
        while idle_rounds < 600:
            events = store.list_after(run_id, cursor)
            if events:
                idle_rounds = 0
                for event in events:
                    cursor = event.seq
                    yield encode_sse(event)
                    if event.terminal:
                        return
            else:
                idle_rounds += 1
                yield encode_heartbeat()
                await asyncio.sleep(0.5)

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str):
    try:
        accepted = store.request_cancel(run_id)
    except KeyError:
        raise HTTPException(404, "run 不存在") from None
    return {"run_id": run_id, "accepted": accepted, "status": store.get(run_id).status}

