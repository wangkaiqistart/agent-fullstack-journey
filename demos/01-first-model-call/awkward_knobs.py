"""一次只调一个采样参数，比较同一问题的真实回答。"""

import argparse

from settings import create_client, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument("--temperature", type=float)
    sampling.add_argument("--top-p", type=float)
    args = parser.parse_args()

    # 不同时传 temperature 和 top_p，便于把变化归因到一个参数。
    if args.top_p is not None:
        if not 0 < args.top_p <= 1:
            raise ValueError("top_p 必须在 (0, 1] 内")
        generation = {"top_p": args.top_p}
    else:
        temperature = 0.2 if args.temperature is None else args.temperature
        if not 0 <= temperature <= 2:
            raise ValueError("temperature 必须在 [0, 2] 内")
        generation = {"temperature": temperature}

    print("本次参数：", generation)
    client, model = create_client()
    with client:
        # 固定输入和输出预算，重复两次；低温也不保证逐字相同。
        for index in range(2):
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "给一个待办清单应用起一个中文名，只输出名称。"}],
                max_completion_tokens=256,
                **generation,
            )
            if not response.choices:
                raise ValueError("响应中没有 choices")
            choice = response.choices[0]
            if choice.finish_reason != "stop" or choice.message.refusal:
                raise ValueError("未获得正常结束的回答")
            if not choice.message.content:
                raise ValueError("消息内容为空")
            print(f"第 {index + 1} 次：{choice.message.content}")


if __name__ == "__main__":
    run(main)
