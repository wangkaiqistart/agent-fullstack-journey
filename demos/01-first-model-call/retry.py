"""只重试暂时性故障；包含首次请求，最多尝试三次。"""

import random
import time

from openai import APIConnectionError, APIStatusError, RateLimitError

from settings import create_client, run


def is_transient(error):
    if isinstance(error, (TimeoutError, ConnectionError, APIConnectionError, RateLimitError)):
        return True
    # SDK 的超时属于 APIConnectionError；其余 HTTP 错误按状态判断。
    return isinstance(error, APIStatusError) and error.status_code in {408, 409, 429, 500, 502, 503, 504}


def call_with_retry(call, attempts=3, *, wait=time.sleep, jitter=None, on_retry=None):
    if attempts < 1:
        raise ValueError("attempts 至少为 1")
    for attempt in range(attempts):
        try:
            return call()
        except Exception as error:
            # 认证、参数、拒答和字段校验错误不会因盲目重试而恢复。
            if not is_transient(error) or attempt == attempts - 1:
                raise
            noise = random.uniform(0, 0.2) if jitter is None else jitter
            delay = min(8, 0.5 * 2 ** attempt) + noise
            if on_retry:
                on_retry(attempt + 1, error, delay)
            wait(delay)


def main():
    client, model = create_client()

    def report(retry_count, error, delay):
        print(f"重试 {retry_count}：{type(error).__name__}，等待 {delay:.2f}s")

    with client:
        response = call_with_retry(
            lambda: client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "用一句中文说明为什么重试需要上限。"}],
                max_completion_tokens=256,
            ),
            on_retry=report,
        )
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    if choice.message.refusal or choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError("未获得完整回答；这类输出错误不会自动重试")
    print(choice.message.content)


if __name__ == "__main__":
    run(main)
