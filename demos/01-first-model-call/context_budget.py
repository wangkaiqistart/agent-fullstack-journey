"""上下文裁剪：保留最近的文本历史，再调用真实模型。

按字符数计算历史预算，不把字符数当成 Token 数。
仅演示普通文本消息；工具调用需要额外保证请求和结果成对保留。
"""

import argparse

from settings import create_client, run


def build_messages(history, task, max_history_chars=12_000):
    """从最新消息向前取连续历史，再拼接 system 和本次任务。"""
    if max_history_chars < 0:
        raise ValueError("历史字符预算不能为负数")

    recent = []
    used = 0
    for message in reversed(history):
        # len(str) 是字符数，不是 UTF-8 字节数，也不是 Token 数。
        size = len(message["content"])
        if used + size > max_history_chars:
            # 到达预算就停止，不跳过这条去捡更早的消息。
            break
        recent.append(message)
        used += size

    return [
        {"role": "system", "content": "你是谨慎的 Coding Agent。根据保留的历史回答，不知道的信息不要猜。"},
        # 扫描时是从新到旧，发送时必须恢复成从旧到新。
        *reversed(recent),
        {"role": "user", "content": task},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-history-chars", type=int, default=100,
        help="历史正文的字符上限；默认用 100 方便观察裁剪（不是模型容量）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只观察本地裁剪，不读取模型配置、不发送请求",
    )
    args = parser.parse_args()

    # 固定教学数据，不发送自己的聊天记录或业务数据。
    history = [
        {"role": "user", "content": "我以前写过一个待办清单程序，使用文件保存任务，也尝试过添加搜索功能。"},
        {"role": "assistant", "content": "可以先从已经熟悉的程序出发，逐步学习模型调用、结构化输出和工具执行。"},
        {"role": "user", "content": "请记住：实验编号是 LAB-001。"},
        {"role": "assistant", "content": "好的，实验编号是 LAB-001。"},
        {"role": "user", "content": "我现在学习上下文预算，请用中文回答。"},
        {"role": "assistant", "content": "好的，本次学习上下文预算，使用中文。"},
    ]
    task = "我正在学习什么？实验编号是什么？只根据收到的历史回答，没有的信息说不知道。"

    # 1. 裁剪只影响 history，system 和本次 task 始终保留。
    messages = build_messages(history, task, args.max_history_chars)
    retained = messages[1:-1]
    before = sum(len(message["content"]) for message in history)
    after = sum(len(message["content"]) for message in retained)
    print(f"历史预算：{args.max_history_chars} 字符")
    print(f"历史消息：{len(history)} → {len(retained)} 条；历史正文：{before} → {after} 字符")
    print("实际发送的消息：")
    for message in messages:
        print(f"  [{message['role']}] {message['content']}")
    if args.dry_run:
        return

    # 2. 默认是真实请求，复用已有 .env 配置，不写死密钥。
    client, model = create_client()
    with client:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            # 这是输出上限，不代表已从模型总容量中扣除了这部分空间。
            max_completion_tokens=1024,
        )

    # 3. 先检查是否完整结束，再读取回答和服务端统计的实际用量。
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    print("finish_reason:", choice.finish_reason)
    if choice.message.refusal:
        raise ValueError("模型拒答")
    if choice.finish_reason != "stop":
        raise ValueError("未获得完整文本，请检查输出上限或接口返回状态")
    if not choice.message.content:
        raise ValueError("消息内容为空")
    print("回答:", choice.message.content)
    if response.usage is not None:
        print("实际输入 Token:", response.usage.prompt_tokens)
        print("实际输出 Token:", response.usage.completion_tokens)


if __name__ == "__main__":
    run(main)
