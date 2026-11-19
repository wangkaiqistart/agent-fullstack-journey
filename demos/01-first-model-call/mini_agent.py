"""最小规划 Agent：真实生成 → 校验 → 一次字段修复 → 展示计划。"""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from business_guard import validate_plan_path
from context_budget import build_messages
from model_adapter import ChatCompletionsAdapter, ResponsesAdapter
from retry import call_with_retry
from schema import PatchPlan
from settings import create_client, run


class MiniAgent:
    def __init__(self, model, workspace):
        self.model = model
        self.workspace = workspace

    def run(self, task):
        messages = build_messages([], task)
        messages[0]["content"] = "你是谨慎的代码审查助手。按指定 Schema 输出计划，只建议，不执行；信息不足时 ask_user。"
        trace_id = uuid4().hex

        def trace(**fields):
            # 只记录状态与定位字段，不保存密钥、请求正文和完整模型输出。
            print(json.dumps({"trace_id": trace_id, **fields}, ensure_ascii=False))

        # 最多两轮生成：首次生成 + 一次字段修复，不无限追问模型。
        for turn in range(2):
            start = time.monotonic()
            retry_count = 0

            def report_retry(count, error, delay):
                nonlocal retry_count
                retry_count = count
                trace(turn=turn + 1, retry_count=count,
                      error_type=type(error).__name__, wait_seconds=round(delay, 3))

            try:
                result = call_with_retry(
                    lambda: self.model.generate(
                        messages, max_tokens=1024, schema=PatchPlan.model_json_schema(),
                    ),
                    attempts=3, on_retry=report_retry,
                )
            except Exception as error:
                trace(turn=turn + 1, retry_count=retry_count,
                      latency=round(time.monotonic() - start, 3),
                      error_type=type(error).__name__, outcome="stopped")
                raise

            fields = {
                "turn": turn + 1, "model_id": result.model,
                "finish_reason": result.finish_reason, "retry_count": retry_count,
                "latency": round(time.monotonic() - start, 3),
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            }
            if result.finish_reason != "stop":
                trace(**fields, outcome="stopped")
                raise ValueError("模型输出未正常完成")
            try:
                plan = PatchPlan.model_validate_json(result.text)
            except ValidationError as error:
                # 只回传字段位置和错误类型，避免把整个校验异常中的输入回显。
                diff = [{"field": list(item["loc"]), "type": item["type"]}
                        for item in error.errors()]
                trace(**fields, schema_diff=diff, outcome="invalid_schema")
                if turn == 1:
                    raise ValueError("修复后仍不符合计划契约，停止") from None
                messages.extend([
                    {"role": "assistant", "content": result.text},
                    {"role": "user", "content": f"请修复字段错误：{json.dumps(diff)}。edit 必须有路径；finish 的路径必须为 null。"},
                ])
                continue

            try:
                validate_plan_path(plan, self.workspace)
            except ValueError:
                trace(**fields, outcome="invalid_path")
                # 路径越界不靠模型承诺恢复，也不进入执行阶段。
                raise
            trace(**fields, schema_diff=[], outcome=plan.action)
            return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", choices=["chat", "responses"], default="chat")
    parser.add_argument("--alternate", action="store_true", help="使用 AGENTOS_ALT_LLM_* 配置")
    args = parser.parse_args()

    workspace = Path(__file__).parent / "assets" / "workspace"
    # 只读固定样本，不扫描或发送实际仓库文件。
    source = (workspace / "src" / "example.py").read_text()
    task = (
        "仓库摘要：一个 Python 文件 src/example.py，尚无测试。\n"
        f"文件内容：\n{source}\n"
        "用户要求：None 输入返回 0，其余输入仍使用 len(x)。请生成低风险修改计划。"
    )
    client, model = create_client(prefix="AGENTOS_ALT_LLM" if args.alternate else "AGENTOS_LLM")
    adapter_type = ChatCompletionsAdapter if args.api == "chat" else ResponsesAdapter
    with client:
        plan = MiniAgent(adapter_type(client, model), workspace).run(task)
    print(plan.model_dump_json(indent=2))
    print("状态：", {"edit": "计划待人工确认", "ask_user": "需要用户补充信息", "finish": "规划结束"}[plan.action])
    print("本例只生成计划，不修改文件。")


if __name__ == "__main__":
    run(main)
