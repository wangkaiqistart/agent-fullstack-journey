"""Responses 工具闭环：function_call → function_call_output → 最终回答。"""

from order_tool import TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMETERS, execute
from settings import create_client, run


def check_response(response):
    print("status:", response.status)
    if response.status != "completed":
        detail = response.incomplete_details
        raise ValueError(f"响应未完成：{detail.reason if detail else response.status}")
    for item in response.output:
        if item.type == "message":
            if any(part.type == "refusal" for part in item.content):
                raise ValueError("模型拒答")


def main():
    client, model = create_client()
    with client:
        instructions = "用中文简短回答，明确订单数据来自本地模拟工具。"
        history = [{"role": "user", "content": "查询 ORD-DEMO-001 的模拟订单状态。"}]

        # 1. Responses 的工具定义是平铺结构。
        response = client.responses.create(
            model=model, instructions=instructions, input=history,
            tools=[{
                "type": "function", "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": TOOL_PARAMETERS, "strict": True,
            }],
            # tool_choice={"type": "function", "name": TOOL_NAME},
            parallel_tool_calls=False,
            max_output_tokens=1024,
            store=False,
        )
        check_response(response)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            raise ValueError("未收到工具请求")

        # 2. 无服务端会话依赖：保留完整输出，包括可能存在的 reasoning 项。
        history.extend(item.model_dump(exclude_none=True) for item in response.output)
        for call in calls:
            result = execute(call.name, call.arguments)
            print("工具请求:", call.name, call.arguments)
            print("工具结果:", result)
            # 用 call_id 关联请求；不要使用输出项的 id。
            history.append({
                "type": "function_call_output", "call_id": call.call_id, "output": result,
            })

        # 3. 第二次调用仍传 instructions；只演示一轮工具执行。
        response = client.responses.create(
            model=model, instructions=instructions, input=history,
            max_output_tokens=1024, store=False,
        )
        check_response(response)
        if any(item.type == "function_call" for item in response.output):
            raise ValueError("示例最多执行一轮工具请求")
        if not response.output_text:
            raise ValueError("没有文本输出")
        print("回答:", response.output_text)


if __name__ == "__main__":
    run(main)

