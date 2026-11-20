"""真实模型：原生 JSON Schema + 本地 Pydantic 再校验。"""

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
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是知识库路由助手。只能输出 AgentDecision。"
                        "有明确答案时 finish；需要检索资料时 search_docs。"
                    ),
                },
                {"role": "user", "content": args.question},
            ],
            max_completion_tokens=512,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_decision",
                    "strict": True,
                    "schema": schema(),
                },
            },
        )
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    if choice.message.refusal:
        raise ValueError("模型拒答，不能进入工具 Loop")
    if choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError(f"输出未完整结束：{choice.finish_reason}")
    result = validate_json(choice.message.content)
    if not result.ok:
        raise ValueError(result.message or "决策校验失败")
    assert isinstance(result.decision, AgentDecision)
    print(json.dumps({"model": model, "decision": result.decision.model_dump()}, ensure_ascii=False, indent=2))
    print("本地 Pydantic 校验通过；这里只展示决策，不执行工具。")


if __name__ == "__main__":
    run(main)
