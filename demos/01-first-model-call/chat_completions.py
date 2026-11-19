"""Chat Completions：messages → choices[0].message。"""

from settings import create_client, run


def main():
    client, model = create_client()
    with client:
        # 1. system 定义行为，user 提交本次问题。
        messages = [
            {"role": "system", "content": "你是代码审查助手，用一句中文回答。"},
            {"role": "user", "content": "def size(x): return len(x) 有什么风险？"},
        ]

        # 2. 真实请求。输出上限包含模型可能使用的推理 token。
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=1024,
        )

        # 3. 先看结束原因，再把消息当作完整答案使用。
        if not response.choices:
            raise ValueError("响应中没有 choices")
        choice = response.choices[0]
        print("finish_reason:", choice.finish_reason)
        if choice.message.refusal:
            raise ValueError("模型拒答")
        if choice.finish_reason != "stop":
            raise ValueError("未获得正常结束的文本，请检查输出上限或工具请求")
        if not choice.message.content:
            raise ValueError("消息内容为空")
        print("回答:", choice.message.content)


if __name__ == "__main__":
    run(main)

