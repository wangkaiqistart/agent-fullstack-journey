"""Chat 工具闭环：tool_calls → 本地执行 → tool 消息 → 最终回答。"""

from order_tool import TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMETERS, execute
from settings import create_client, run


def main():
    client, model = create_client()
    with client:
        messages = [
            {"role": "system", "content": "用中文简短回答，明确订单数据来自本地模拟工具。"},
            {"role": "user", "content": "查询 ORD-DEMO-001 的模拟订单状态。"},
        ]

        # 1. Chat 的工具定义嵌套在 function 里；指定工具便于稳定观察闭环。
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[{"type": "function", "function": {
                "name": TOOL_NAME, "description": TOOL_DESCRIPTION,
                "parameters": TOOL_PARAMETERS, "strict": True,
            }}],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            parallel_tool_calls=False,
            max_completion_tokens=1024,
        )
        if not response.choices:
            raise ValueError("响应中没有 choices")
        choice = response.choices[0]
        print("第一轮 finish_reason:", choice.finish_reason)
        if choice.message.refusal:
            raise ValueError("模型拒答")
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            raise ValueError("未收到完整工具请求，不执行工具")

        # 2. 保留 assistant 请求，再回传每个工具的执行结果。
        messages.append(choice.message.model_dump(exclude_none=True))
        for call in choice.message.tool_calls:
            if call.type != "function":
                raise ValueError("仅支持 function 工具")
            result = execute(call.function.name, call.function.arguments)
            print("工具请求:", call.function.name, call.function.arguments)
            print("工具结果:", result)
            messages.append({
                "role": "tool", "tool_call_id": call.id, "content": result,
            })

        # 3. 再请求一次真实模型，让它根据工具结果回答。
        response = client.chat.completions.create(
            model=model, messages=messages, max_completion_tokens=1024,
        )
        if not response.choices:
            raise ValueError("响应中没有 choices")
        choice = response.choices[0]
        print("第二轮 finish_reason:", choice.finish_reason)
        if choice.message.refusal:
            raise ValueError("模型拒答")
        if choice.finish_reason != "stop" or not choice.message.content:
            raise ValueError("未获得完整文本回答")
        print("回答:", choice.message.content)


if __name__ == "__main__":
    run(main)

