"""真实模型示例：System Prompt + Few-shot + 不可信代码区域。"""

import argparse

from prompt_contract import CODE_REVIEW_PROMPT, build_messages
from settings import create_client, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="def size(x): return len(x)")
    args = parser.parse_args()
    client, model = create_client()
    messages = build_messages(args.code)
    with client:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=512,
        )
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    if choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError(f"模型未正常完成：finish_reason={choice.finish_reason}")
    print(f"prompt={CODE_PROMPT_NAME} version={CODE_PROMPT_VERSION} model={model}")
    print(choice.message.content)


# 只从定义读取标识，避免运行时把整段 System Prompt 打到日志。
CODE_PROMPT_NAME = CODE_REVIEW_PROMPT.name
CODE_PROMPT_VERSION = CODE_REVIEW_PROMPT.version


if __name__ == "__main__":
    run(main)
