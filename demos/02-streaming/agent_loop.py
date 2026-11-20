"""最小 Agent Loop：生产业务事件，不操作 HTTP，不拼 SSE。"""

import asyncio
from collections.abc import Awaitable, Callable

from run_store import InMemoryRunStore
from stream_model import StreamingModel


async def run_agent(
    model: StreamingModel,
    messages: list[dict[str, str]],
    store: InMemoryRunStore,
    *,
    run_id: str | None = None,
    on_event: Callable[[object], Awaitable[None] | None] | None = None,
):
    run_id = run_id or store.create()

    async def publish(event_type, data=None):
        event = store.publish(run_id, event_type, data)
        if on_event:
            result = on_event(event)
            if asyncio.iscoroutine(result):
                await result
        return event

    await publish("run.started", {"status": "running"})
    await publish("task.started", {"message_count": len(messages)})
    try:
        saw_finish = False
        async for model_event in model.stream(messages):
            if store.is_cancel_requested(run_id):
                await publish("run.cancelled", {"reason": "user_requested"})
                return run_id
            if model_event.type in {"text.delta", "model.finished", "model.usage"}:
                await publish(model_event.type, model_event.data)
            if model_event.type == "model.finished":
                saw_finish = True
                if model_event.data.get("finish_reason") != "stop":
                    await publish("run.failed", {
                        "code": "MODEL_INCOMPLETE",
                        "stage": "model.finished",
                        "retryable": False,
                    })
                    return run_id
        if not saw_finish:
            await publish("run.failed", {
                "code": "STREAM_ENDED_WITHOUT_FINISH",
                "stage": "model.stream",
                "retryable": False,
            })
            return run_id
        await publish("run.completed", {"status": "ok"})
        return run_id
    except asyncio.CancelledError:
        # 取消是控制信号；先记录终态，再继续向上传播取消。
        if store.get(run_id).status not in {"completed", "failed", "cancelled"}:
            await publish("run.cancelled", {"reason": "task_cancelled"})
        raise
    except Exception as error:
        if store.get(run_id).status not in {"completed", "failed", "cancelled"}:
            await publish("run.failed", {
                "code": "STREAM_ERROR",
                "stage": "model.stream",
                "retryable": False,
                "error_type": type(error).__name__,
            })
        raise

