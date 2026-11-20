"""真实模型：Responses 的 text.format + 本地 Pydantic 再校验。"""

import argparse
import json

from decision import AgentDecision, schema
from settings import create_client, run
from validation import validate_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", default="公司差旅报销需要哪些材料？")
    args = parser.parse_args()
    client, model = create_client()
    with client:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": "你是知识库路由助手，只输出 AgentDecision。"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": args.question}],
                },
            ],
            max_output_tokens=512,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "agent_decision",
                    "strict": True,
                    "schema": schema(),
                }
            },
        )
    if response.status != "completed":
        raise ValueError(f"Responses 未完成：{response.status}")
    if not response.output_text:
        raise ValueError("Responses 没有文本")
    result = validate_json(response.output_text)
    if not result.ok:
        raise ValueError(result.message or "决策校验失败")
    assert isinstance(result.decision, AgentDecision)
    print(json.dumps({"model": model, "decision": result.decision.model_dump()}, ensure_ascii=False, indent=2))
    print("本地 Pydantic 校验通过；这里只展示决策，不执行工具。")


if __name__ == "__main__":
    run(main)
