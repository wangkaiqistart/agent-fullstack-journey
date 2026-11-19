"""缩小输出预算，观察 finish_reason；截断内容不作为完整答案。"""

import argparse

from settings import create_client, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--budget-field", choices=["max_completion_tokens", "max_tokens"], default="max_completion_tokens")
    args = parser.parse_args()
    if args.max_tokens < 1:
        raise ValueError("输出预算至少为 1")

    client, model = create_client()
    with client:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用中文详细解释上下文预算，至少写十条建议，每条不少于五十字。"}],
            **{args.budget_field: args.max_tokens},
        )
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    print("finish_reason:", choice.finish_reason)
    if response.usage:
        print("实际输出 Token:", response.usage.completion_tokens)
        if response.usage.completion_tokens > args.max_tokens:
            raise ValueError("服务端报告的输出用量超过请求上限，请核对网关对预算字段的支持；不采用此结果")
    if choice.message.refusal:
        raise ValueError("模型拒答")
    if choice.finish_reason == "length":
        # 上限可能同时消耗在推理和可见文字上，截断时也可能没有正文。
        print("输出达到上限：丢弃不完整答案，调整预算或拆分任务后再请求。")
        return
    if choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError("未获得完整文本")
    print("完整回答：", choice.message.content)


if __name__ == "__main__":
    run(main)
