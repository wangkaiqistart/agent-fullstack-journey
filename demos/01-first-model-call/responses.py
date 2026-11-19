"""Responses：input → output 中的多种类型项。"""

from settings import create_client, run


def main():
    client, model = create_client()
    with client:
        # 1. instructions 定义行为，input 提交消息。
        response = client.responses.create(
            model=model,
            instructions="你是代码审查助手，用一句中文回答。",
            input=[{"role": "user", "content": "def size(x): return len(x) 有什么风险？"}],
            max_output_tokens=1024,
            store=False,
        )

        # 2. completed 表示本次响应完成，incomplete 要继续检查原因。
        print("status:", response.status)
        if response.status != "completed":
            detail = response.incomplete_details
            reason = detail.reason if detail else response.status
            raise ValueError(f"响应未完成：{reason}")

        # 3. output 可能包含 message、reasoning、function_call 等项。
        for item in response.output:
            print("output.type:", item.type)
            if item.type == "function_call":
                raise ValueError("本示例不执行工具，请运行 responses_tools.py")
            if item.type == "message":
                if any(part.type == "refusal" for part in item.content):
                    raise ValueError("模型拒答")

        # output_text 是 SDK 汇总文本的便捷属性，并非完整输出结构。
        if not response.output_text:
            raise ValueError("没有文本输出")
        print("回答:", response.output_text)


if __name__ == "__main__":
    run(main)

