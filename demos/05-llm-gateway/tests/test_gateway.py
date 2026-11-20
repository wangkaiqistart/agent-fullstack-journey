"""Gateway 协议隔离、重试/fallback、模板和流式边界测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway_core import Gateway, GatewayError
from protocol import ChatRequest, Message
from provider import ProviderChunk, ProviderResult, ProviderUsage


class FakeProvider:
    def __init__(self, name, results=None, stream_chunks=None):
        self.name = name
        self.results = list(results or [])
        self.stream_chunks = list(stream_chunks or [])
        self.calls = 0

    def complete(self, _messages, *, max_output_tokens):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def stream(self, _messages, *, max_output_tokens):
        self.calls += 1
        yield from self.stream_chunks


def result(text):
    return ProviderResult(text, ProviderUsage(10, 4, 14), "stop")


class GatewayTests(unittest.TestCase):
    def request(self, **kwargs):
        return ChatRequest(messages=[Message(role="user", content="问题")], **kwargs)

    def test_template_missing_and_unknown_model_are_protocol_errors(self):
        gateway = Gateway({"primary": FakeProvider("primary", [result("ok")])})
        with self.assertRaisesRegex(GatewayError, "missing_prompt_variable"):
            gateway.complete(self.request(prompt_template="kb-qa", variables={}))
        with self.assertRaisesRegex(GatewayError, "unknown_model"):
            gateway.complete(self.request(model="does-not-exist"))

    def test_transient_error_retries_once_then_uses_backup(self):
        primary = FakeProvider("primary", [TimeoutError(), TimeoutError()])
        backup = FakeProvider("backup", [result("备用答案")])
        gateway = Gateway({"primary": primary, "backup": backup})
        response = gateway.complete(self.request())
        self.assertEqual((response.provider, response.fallback_used, response.attempts), ("backup", True, 3))
        self.assertEqual((primary.calls, backup.calls), (2, 1))

    def test_schema_failure_does_not_fallback_silently(self):
        primary = FakeProvider("primary", [result('{"action":"finish","query":null}')])
        backup = FakeProvider("backup", [result('{"action":"finish","query":null,"answer":"备用"}')])
        gateway = Gateway({"primary": primary, "backup": backup})
        with self.assertRaisesRegex(GatewayError, "schema_validation_failed"):
            gateway.complete(self.request(schema_name="agent_decision"))
        self.assertEqual(backup.calls, 0)

    def test_stream_forwards_chunks_without_switching_after_first_delta(self):
        primary = FakeProvider("primary", stream_chunks=[ProviderChunk("甲"), ProviderChunk("乙"), ProviderChunk("", "stop")])
        traces = []
        gateway = Gateway({"primary": primary}, trace_sink=traces.append)
        events = list(gateway.stream(self.request()))
        self.assertEqual([event["type"] for event in events], ["content.delta", "content.delta", "response.completed"])
        self.assertEqual("".join(event["data"].get("delta", "") for event in events), "甲乙")
        self.assertEqual(traces[0].status, "completed")

    def test_trace_records_success(self):
        traces = []
        gateway = Gateway({"primary": FakeProvider("primary", [result("ok")])}, trace_sink=traces.append)
        response = gateway.complete(self.request())
        self.assertEqual(traces[0].trace_id, response.trace_id)
        self.assertEqual((traces[0].status, traces[0].attempts), ("completed", 1))


if __name__ == "__main__":
    unittest.main()
