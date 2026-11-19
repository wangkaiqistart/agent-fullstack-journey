"""Responses 多模态：同一条输入同时包含 input_text 和 input_image。"""

from image_input import read_image_input
from settings import create_client, run


def main():
    # 1. 和 Chat 示例发送同一张图片、同一个问题，方便对比协议。
    image_url, question = read_image_input()
    client, model = create_client()
    with client:
        response = client.responses.create(
            model=model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                    {
                        "type": "input_image",
                        # 2. Responses 的 image_url 直接是字符串，无需再套 url 字段。
                        "image_url": image_url,
                        "detail": "auto",  # 自动选择图片处理精度。
                    },
                ],
            }],
            max_output_tokens=1024,
            store=False,
        )

        # 3. 完整响应可能包含 reasoning、message 等多种输出项。
        print("status:", response.status)
        if response.status != "completed":
            detail = response.incomplete_details
            raise ValueError(f"响应未完成：{detail.reason if detail else response.status}")
        for item in response.output:
            print("output.type:", item.type)
            if item.type == "message":
                if any(part.type == "refusal" for part in item.content):
                    raise ValueError("模型拒答")
            if item.type == "function_call":
                raise ValueError("本示例不执行工具")

        # output_text 汇总输出中的文本，不包含图片二进制。
        if not response.output_text:
            raise ValueError("没有文本输出")
        print("回答:", response.output_text)


if __name__ == "__main__":
    run(main)
