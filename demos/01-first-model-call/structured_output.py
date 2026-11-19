"""真实模型生成 JSON → 本地 Schema 校验 → 工作区路径校验。"""

from pathlib import Path

from pydantic import ValidationError

from business_guard import validate_plan_path
from schema import PatchPlan
from settings import create_client, run


def main():
    client, model = create_client()
    with client:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是代码审查助手，输出修改计划；只建议，不执行。"},
                {"role": "user", "content": "src/example.py 中 def size(x): return len(x)。要求 None 输入返回 0，请生成低风险修改计划。"},
            ],
            max_completion_tokens=1024,
            # 在请求里启用结构约束，定义 BaseModel 本身不会影响服务端生成。
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "patch_plan", "strict": True,
                    "schema": PatchPlan.model_json_schema(),
                },
            },
        )
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    if choice.message.refusal:
        raise ValueError("模型拒答")
    if choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError("未获得完整 JSON，停止解析")
    try:
        plan = PatchPlan.model_validate_json(choice.message.content)
    except ValidationError:
        # 不直接打印异常，以免错误正文回显原始输入。
        raise ValueError("修改计划未通过本地字段或业务校验") from None
    workspace = Path(__file__).parent / "assets" / "workspace"
    validate_plan_path(plan, workspace)
    print(plan.model_dump_json(indent=2))
    print("字段和路径校验通过；没有修改文件。")


if __name__ == "__main__":
    run(main)
