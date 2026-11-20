"""阶段项目的路由、Provider 能力、fallback 和兼容协议测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import GatewayConfig, ProviderConfig
from app.gateway import GatewayService
from app.providers import Chunk
from app.schemas import ChatCompletionRequest, Message, Usage
from app.usage import UsageStore


class FakeProvider:
    def __init__(self, name, model, results=None, chunks=None, capabilities=None):
        self.name = name
        self.model = model
        self.results = list(results or [])
        self.chunks = list(chunks or [])
        self.capabilities = frozenset(capabilities or {"chat", "streaming"})
        self.calls = 0

    def complete(self, _messages, *, max_tokens):
        self.calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, Usage(prompt_tokens=2, completion_tokens=3, total_tokens=5), "stop"

    def stream(self, _messages, *, max_tokens):
        self.calls += 1
        yield from self.chunks


class GatewayProjectTests(unittest.TestCase):
    def setUp(self):
        self.config = GatewayConfig(
            providers={
                "primary": ProviderConfig("primary", "https://x", "key", "model-a", 10, frozenset({"chat", "streaming"})),
                "backup": ProviderConfig("backup", "https://y", "key", "model-b", 20, frozenset({"chat", "streaming"})),
            },
            model_routes={"default": ["primary", "backup"]},
            required_capabilities={"default": {"chat"}},
            max_attempts=2,
        )

    def request(self, **kwargs):
        return ChatCompletionRequest(model=kwargs.pop("model", "default"), messages=[Message(role="user", content="问题")], **kwargs)

    def test_primary_retry_then_backup_and_usage_record(self):
        primary = FakeProvider("primary", "model-a", [TimeoutError(), TimeoutError()])
        backup = FakeProvider("backup", "model-b", ["备用答案"])
        with tempfile.TemporaryDirectory() as directory:
            service = GatewayService(self.config, {"primary": primary, "backup": backup}, UsageStore(Path(directory) / "usage.db"))
            result = service.complete(self.request())
        self.assertEqual((result.provider, result.fallback_used, result.attempts), ("backup", True, 3))

    def test_stream_requires_capability_and_forwards_chunks(self):
        primary = FakeProvider("primary", "model-a", chunks=[Chunk("甲"), Chunk("乙", "stop")])
        with tempfile.TemporaryDirectory() as directory:
            store = UsageStore(Path(directory) / "usage.db")
            service = GatewayService(self.config, {"primary": primary}, store)
            chunks = list(service.stream(self.request()))
            self.assertEqual(store.recent(1)[0]["status"], "completed")
        self.assertEqual([chunk.delta for chunk in chunks], ["甲", "乙"])

    def test_unknown_logical_model_is_rejected(self):
        primary = FakeProvider("primary", "model-a", ["答案"])
        with tempfile.TemporaryDirectory() as directory:
            service = GatewayService(self.config, {"primary": primary}, UsageStore(Path(directory) / "usage.db"))
            with self.assertRaisesRegex(ValueError, "unknown_model"):
                service.complete(self.request(model="missing"))


if __name__ == "__main__":
    unittest.main()
