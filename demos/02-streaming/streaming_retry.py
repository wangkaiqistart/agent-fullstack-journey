"""流式连接重试：已有业务事件后只重放，不重新生成。"""

import asyncio
# time：这里用 time.monotonic() 计时
import time
# Awaitable：可以被 await 的对象；Callable：可以被调用的对象（如函数）
from collections.abc import Awaitable, Callable


def retryable_status(status: int) -> bool:
    """判断 HTTP 状态码是否值得重试（本文件的 connect_with_retry 目前没有调用它）。"""
    # 408 请求超时；409 冲突；429 请求太频繁（限流）；500/502/503/504 服务端或网关出错
    # 这些多是暂时性故障，稍后重试可能成功；而 401（密钥错误）、400（参数错误）重试也没用
    return status in {408, 409, 429, 500, 502, 503, 504}


async def connect_with_retry(
    # connect：负责建立连接的异步函数；成功就返回结果，失败就抛出异常
    connect: Callable[[], Awaitable[object]],
    *,  # 星号之后的参数必须写参数名，例如 max_attempts=3，避免传错位置
    max_attempts: int = 3,  # 最多尝试几次（含第一次）
    max_total_seconds: float = 10,  # 总时间预算：重试加等待加起来不超过这个秒数
    # 判断函数：是否已经产生过“不可重复”的业务事件（如已经给用户看了一段文字）
    # 默认永远返回 False，表示还没产生
    emitted_business_event: Callable[[], bool] = lambda: False,
    # 等待函数，默认真的等待；测试时可以换成“不真等待”的版本，让测试跑得快
    sleep=asyncio.sleep,
):
    """只在未产生不可重复事件前重试，限制次数与总时间。"""
    # monotonic：单调时钟，只会往前走，不受系统改时间影响，适合算时间间隔
    # deadline（截止时刻）= 现在 + 总预算
    deadline = time.monotonic() + max_total_seconds
    # attempt 依次是 0、1、2（max_attempts=3 时）
    for attempt in range(max_attempts):
        try:
            # 成功就直接返回，整个函数结束
            return await connect()
        except Exception:
            # 两种情况不再重试，把错误原样抛出（raise 单独使用 = 重新抛出刚捕获的异常）：
            # 1. 已经产生过业务事件：重试会让模型重新生成，造成内容重复
            # 2. 已经是最后一次尝试：没有机会了
            if emitted_business_event() or attempt == max_attempts - 1:
                raise
            # 指数退避（exponential backoff）：每失败一次，等待时间翻倍
            # 第 1 次失败后等 0.5 秒，第 2 次失败后等 1 秒；min(8.0, ...) 给单次等待设上限 8 秒
            delay = min(8.0, 0.5 * 2**attempt)
            # 距离截止时刻还剩多少秒
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # 总预算用完了，不再重试；from None 隐藏原始异常的堆栈，只显示这条提示
                raise TimeoutError("连接重试超过总时间预算") from None
            # 等待时间取“计划等待”和“剩余预算”中较小的，保证总时间不超标
            await sleep(min(delay, remaining))
    # 正常情况下代码不会走到这里：循环里要么 return，要么 raise
    # 写这一行是为了让类型检查工具确认“函数一定有返回或抛错”
    raise AssertionError("unreachable")
