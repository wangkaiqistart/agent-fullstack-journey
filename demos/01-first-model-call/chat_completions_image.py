"""Chat 多模态：同一条 user 消息同时包含 text 和 image_url。"""

from image_input import read_image_input
from settings import create_client, run


def main():
    # 1. 本地图片转成 data URL；传入 HTTPS 地址时直接使用该地址。
    image_url, question = read_image_input()
    client, model = create_client()
    with client:
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                # 2. 纯文本时 content 可以是字符串；多模态时改为内容块列表。
                "content": [
                    {"type": "text", "text": question},
                    {
                        "type": "image_url",
                        # Chat 的地址放在 image_url.url，比 Responses 多嵌套一层。
                        "image_url": {"url": image_url, "detail": "auto"},
                    },
                ],
            }],
            max_completion_tokens=1024,
        )

        # 3. 图片是输入，回答仍是文本；先确认正常结束，再读取答案。
        if not response.choices:
            raise ValueError("响应中没有 choices")
        choice = response.choices[0]
        print("finish_reason:", choice.finish_reason)
        if choice.message.refusal:
            raise ValueError("模型拒答")
        if choice.finish_reason != "stop":
            raise ValueError("未获得正常结束的文本，请检查结束原因与输出上限")
        if not choice.message.content:
            raise ValueError("消息内容为空")
        print("回答:", choice.message.content)


if __name__ == "__main__":
    run(main)

