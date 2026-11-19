"""离线故障实验：确定性地模拟前两次超时，第三次成功。"""

from retry import call_with_retry


def main():
    results = iter([TimeoutError(), TimeoutError(), "计划生成成功"])

    def simulated_call():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    # 注入等待函数与抖动值：只打印计划，不真正等待、不调用模型。
    result = call_with_retry(
        simulated_call,
        wait=lambda delay: print(f"计划等待 {delay:.1f}s"),
        jitter=0,
    )
    print(result)


if __name__ == "__main__":
    main()
