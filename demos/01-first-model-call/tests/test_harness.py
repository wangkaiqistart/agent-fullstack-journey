"""离线边界测试；替身仅用于注入故障，示例入口默认调用真实模型。"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from openai import APIStatusError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from business_guard import validate_workspace_path
from context_budget import build_messages
from mini_agent import MiniAgent
from model_adapter import ChatCompletionsAdapter, ModelResult, ResponsesAdapter
from retry import call_with_retry, is_transient
from schema import PatchPlan
from settings import create_client


VALID = {"action": "edit", "file_path": "src/example.py", "reason": "增加空值判断", "risk": "low"}


class HarnessTests(unittest.TestCase):
    def test_schema_rejects_invalid_business_fields(self):
        PatchPlan.model_validate(VALID)
        for change in [
            {"file_path": None}, {"risk": "safe"}, {"approved": True},
            {"action": "finish"}, {"reason": "  "}, {"reason": 123},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                PatchPlan.model_validate({**VALID, **change})

    def test_path_scope_and_symlinks(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            workspace = Path(root)
            (workspace / "src").mkdir()
            for value in ["../x.py", "src/../../x.py", "/tmp/x.py", "C:/x.py", "src\\x.py", ".env", ".", "src/x.txt"]:
                with self.subTest(path=value), self.assertRaises(ValueError):
                    validate_workspace_path(value, workspace)
            self.assertEqual(validate_workspace_path("src/new.py", workspace), workspace.resolve() / "src/new.py")
            (workspace / "src" / "linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                validate_workspace_path("src/linked/x.py", workspace)
            (workspace / "src" / "inside.py").symlink_to(workspace / "private.py")
            with self.assertRaises(ValueError):
                validate_workspace_path("src/inside.py", workspace)

    def test_context_budget_boundaries(self):
        history = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "新回答"}]
        self.assertEqual(build_messages(history, "任务", 3)[1:-1], history[-1:])
        self.assertEqual(build_messages(history, "任务", 6)[1:-1], history)
        self.assertEqual(build_messages(history, "任务", 0)[1:-1], [])
        self.assertEqual(build_messages(history, "任务", 2)[1:-1], [])
        with self.assertRaises(ValueError):
            build_messages(history, "任务", -1)

    def test_retry_success_exhaustion_and_permanent_failure(self):
        for sequence, expected_waits, error in [
            ([TimeoutError(), TimeoutError(), "ok"], [0.5, 1.0], None),
            ([TimeoutError(), TimeoutError(), TimeoutError()], [0.5, 1.0], TimeoutError),
            ([ValueError()], [], ValueError),
        ]:
            results = iter(sequence)
            waits = []
            def call():
                value = next(results)
                if isinstance(value, Exception):
                    raise value
                return value
            if error:
                with self.assertRaises(error):
                    call_with_retry(call, wait=waits.append, jitter=0)
            else:
                self.assertEqual(call_with_retry(call, wait=waits.append, jitter=0), "ok")
            self.assertEqual(waits, expected_waits)
        with self.assertRaises(ValueError):
            call_with_retry(lambda: None, attempts=0)

    def test_sdk_http_errors_are_classified(self):
        for status in [400, 401, 403, 404, 408, 409, 429, 500, 502, 503, 504]:
            response = NS(status_code=status, headers={}, request=NS())
            error = APIStatusError("test", response=response, body=None)
            self.assertEqual(is_transient(error), status in {408, 409, 429, 500, 502, 503, 504})

    def test_output_budget_violation_is_rejected(self):
        from output_limit import main
        client = MagicMock()
        client.chat.completions.create.return_value = NS(
            choices=[NS(finish_reason="stop", message=NS(refusal=None, content="oversized"))],
            usage=NS(completion_tokens=100),
        )
        with patch("output_limit.create_client", return_value=(client, "test")), \
                patch("sys.argv", ["output_limit.py", "--max-tokens", "32"]), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "超过请求上限"):
            main()

    def test_adapters_preserve_schema_and_reject_unfinished_output(self):
        captured = []
        chat = NS(choices=[NS(finish_reason="stop", message=NS(content="ok", refusal=None))], model="test", usage=None)
        responses = NS(status="completed", output=[], output_text="ok", model="test", usage=None)
        def chat_create(**options):
            captured.append(options)
            return chat
        def responses_create(**options):
            captured.append(options)
            return responses
        client = NS(chat=NS(completions=NS(create=chat_create)), responses=NS(create=responses_create))
        messages = [{"role": "user", "content": "问题"}]
        schema = PatchPlan.model_json_schema()
        for adapter in [ChatCompletionsAdapter(client, "test"), ResponsesAdapter(client, "test")]:
            self.assertEqual(adapter.generate(messages, schema=schema).text, "ok")
        self.assertEqual(captured[0]["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(captured[1]["text"]["format"]["schema"], schema)
        chat.choices[0].finish_reason = "length"
        with self.assertRaises(ValueError):
            ChatCompletionsAdapter(client, "test").generate(messages)
        responses.output = [NS(type="function_call")]
        with self.assertRaises(ValueError):
            ResponsesAdapter(client, "test").generate(messages)
        responses.output = [NS(type="message", content=[NS(type="refusal")])]
        with self.assertRaises(ValueError):
            ResponsesAdapter(client, "test").generate(messages)

    def test_agent_repairs_once_and_stops_on_unsafe_path(self):
        class TestModel:
            def __init__(self, answers):
                self.answers = iter(answers)
                self.calls = 0
            def generate(self, messages, **options):
                self.calls += 1
                return ModelResult(json.dumps(next(self.answers)), "stop", "test", 1, 1)
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            model = TestModel([{"invalid": True}, VALID])
            self.assertEqual(MiniAgent(model, Path(root)).run("任务").action, "edit")
            self.assertEqual(model.calls, 2)
            model = TestModel([{}, {}])
            with self.assertRaises(ValueError):
                MiniAgent(model, Path(root)).run("任务")
            self.assertEqual(model.calls, 2)
            model = TestModel([{**VALID, "file_path": "../outside.py"}])
            with self.assertRaises(ValueError):
                MiniAgent(model, Path(root)).run("任务")
            self.assertEqual(model.calls, 1)

    def test_settings_supports_alternate_provider_without_changing_default(self):
        config = {f"{prefix}_{key}": value
                  for prefix in ["AGENTOS_LLM", "AGENTOS_ALT_LLM"]
                  for key, value in [("BASE_URL", "https://example.invalid/v1"), ("API_KEY", "test-key"), ("MODEL", prefix)]}
        with patch.dict("os.environ", config, clear=True), patch("settings.load_dotenv"), patch("settings.OpenAI"):
            self.assertEqual(create_client()[1], "AGENTOS_LLM")
            self.assertEqual(create_client("AGENTOS_ALT_LLM")[1], "AGENTOS_ALT_LLM")


if __name__ == "__main__":
    unittest.main()
