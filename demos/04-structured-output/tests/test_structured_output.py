"""Structured Output 的协议、纠错和降级边界测试。"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decision import AgentDecision
from fallback import CachedDecision, choose_result
from repair_loop import repair_until_valid
from validation import validate_json


class StructuredOutputTests(unittest.TestCase):
    def test_schema_and_business_rules_are_strict(self):
        self.assertEqual(AgentDecision(action="finish", query=None, answer="已完成").action, "finish")
        for raw in [
            '{"action":"finish","query":null}',
            '{"action":"search_docs","query":"问题","answer":"提前回答"}',
            '{"action":"unknown","query":null,"answer":null}',
            '{"action":"finish","query":null,"answer":"好","extra":true}',
        ]:
            with self.subTest(raw=raw):
                self.assertFalse(validate_json(raw).ok)

    def test_validation_keeps_error_layers(self):
        self.assertEqual(validate_json("{bad").error_kind, "json_syntax")
        self.assertEqual(
            validate_json('{"action":"finish","query":null}').error_kind,
            "schema_or_business",
        )

    def test_repair_is_bounded_and_does_not_execute_tools(self):
        calls = []
        result, count = repair_until_valid(
            "{bad",
            lambda feedback: calls.append(feedback) or '{"action":"finish","query":null,"answer":"完成"}',
            max_repairs=2,
        )
        self.assertTrue(result.ok)
        self.assertEqual(count, 1)
        self.assertEqual(len(calls), 1)

        result, count = repair_until_valid("{bad", lambda _feedback: "{bad", max_repairs=2)
        self.assertFalse(result.ok)
        self.assertEqual(count, 2)

    def test_fallback_requires_same_key_version_fresh_read_only_cache(self):
        decision = AgentDecision(action="finish", query=None, answer="缓存答案")
        now = datetime.now(timezone.utc)
        cache = CachedDecision("task-1", "1", now + timedelta(minutes=1), decision)
        degraded = choose_result(None, task_key="task-1", protocol_version="1", now=now, cache=cache)
        self.assertEqual((degraded.status, degraded.decision), ("DEGRADED", decision))
        failed = choose_result(None, task_key="task-2", protocol_version="1", now=now, cache=cache)
        self.assertEqual((failed.status, failed.decision), ("FAILED", None))


if __name__ == "__main__":
    unittest.main()
