"""流式协议与状态边界测试；不调用真实模型。"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_loop import run_agent
from cancellation import request_cancel
from checkpoint import Checkpoint, load_checkpoint, save_checkpoint
from events import RunEvent
from run_store import InMemoryRunStore
from sse_codec import SSEParser, encode_heartbeat, encode_sse, parse_chunks
from stream_model import ModelStreamEvent, normalize_chat_stream
from streaming_retry import connect_with_retry


class FakeModel:
    def __init__(self, events):
        self.events = events

    async def stream(self, _messages):
        for event in self.events:
            await asyncio.sleep(0)
            yield event


class StreamingTests(unittest.TestCase):
    def test_sse_roundtrip_unicode_split_and_heartbeat(self):
        event = RunEvent(run_id="run_1", seq=7, type="text.delta", data={"delta": "你好\n世界\\"})
        encoded = encode_sse(event)
        chunks = [encoded[:2], encoded[2:9], encoded[9:17], encoded[17:]]
        self.assertEqual(parse_chunks(chunks), [event])
        self.assertEqual(parse_chunks([encode_heartbeat()]), [])

    def test_sse_ignores_invalid_or_unknown_event(self):
        bad = b"event: unknown\ndata: {\"type\":\"unknown\"}\n\n"
        self.assertEqual(parse_chunks([bad]), [])

    def test_store_sequences_and_single_terminal(self):
        store = InMemoryRunStore()
        run_id = store.create()
        self.assertEqual(store.publish(run_id, "run.started").seq, 0)
        self.assertEqual(store.publish(run_id, "run.completed").seq, 1)
        with self.assertRaises(ValueError):
            store.publish(run_id, "text.delta", {"delta": "late"})
        self.assertEqual([event.seq for event in store.list_after(run_id, 0)], [1])

    def test_agent_completes_and_maps_incomplete_to_failed(self):
        async def run():
            store = InMemoryRunStore()
            await run_agent(FakeModel([
                ModelStreamEvent("text.delta", {"delta": "好"}),
                ModelStreamEvent("model.finished", {"finish_reason": "stop"}),
            ]), [], store)
            state = store.get(next(iter(store._runs)))
            self.assertEqual(state.status, "completed")
            self.assertEqual([e.type for e in state.events], ["run.started", "task.started", "text.delta", "model.finished", "run.completed"])

            failed = InMemoryRunStore()
            await run_agent(FakeModel([ModelStreamEvent("model.finished", {"finish_reason": "length"})]), [], failed)
            failed_state = failed.get(next(iter(failed._runs)))
            self.assertEqual(failed_state.status, "failed")
            self.assertEqual(failed_state.events[-1].data["code"], "MODEL_INCOMPLETE")
        asyncio.run(run())

    def test_agent_cooperative_cancel_and_cancel_state_machine(self):
        async def run():
            store = InMemoryRunStore()
            run_id = store.create()
            store.request_cancel(run_id)
            await run_agent(FakeModel([ModelStreamEvent("text.delta", {"delta": "不会发送"})]), [], store, run_id=run_id)
            self.assertEqual(store.get(run_id).status, "cancelled")
        asyncio.run(run())
        self.assertEqual(request_cancel("running"), "cancelling")
        self.assertEqual(request_cancel("completed"), "completed")

    def test_checkpoint_roundtrip(self):
        checkpoint = Checkpoint(version=1, run_id="run_1", loop_step="tool", completed=["search"], next_cursor="2", context_digest="sha256:x", tool_state=[{"call_id": "c1", "sent": True}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(path, checkpoint)
            self.assertEqual(load_checkpoint(path), checkpoint)

    def test_connection_retry_stops_after_business_event(self):
        async def run():
            calls = 0
            async def connect():
                nonlocal calls
                calls += 1
                raise ConnectionError("offline")
            with self.assertRaises(ConnectionError):
                await connect_with_retry(connect, emitted_business_event=lambda: True, sleep=lambda _: asyncio.sleep(0))
            self.assertEqual(calls, 1)
            calls = 0
            waits = []
            async def recover():
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise ConnectionError("temporary")
                return "connected"
            async def record_sleep(delay):
                waits.append(delay)
            self.assertEqual(await connect_with_retry(recover, sleep=record_sleep), "connected")
            self.assertEqual(calls, 3)
            self.assertEqual(waits, [0.5, 1.0])
        asyncio.run(run())

    def test_normalize_vendor_chunks(self):
        chunks = [
            NS(choices=[], usage=None),
            NS(choices=[NS(delta=NS(content=None), finish_reason=None)], usage=None),
            NS(choices=[NS(delta=NS(content="你"), finish_reason=None)], usage=None),
            NS(choices=[NS(delta=NS(content="好"), finish_reason="stop")], usage=None),
            NS(choices=[], usage=NS(model_dump=lambda mode: {"total_tokens": 3})),
        ]
        async def run():
            return [event async for event in normalize_chat_stream(_AsyncItems(chunks))]
        events = asyncio.run(run())
        self.assertEqual([event.type for event in events], ["text.delta", "text.delta", "model.finished", "model.usage"])


class _AsyncItems:
    def __init__(self, items): self.items = items
    def __aiter__(self): return self
    async def __anext__(self):
        if not self.items: raise StopAsyncIteration
        return self.items.pop(0)


if __name__ == "__main__":
    unittest.main()
