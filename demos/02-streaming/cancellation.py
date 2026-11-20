"""协作式取消与状态机；断开订阅不等于取消 Run。"""

import asyncio


class CancelToken:
    def __init__(self):
        self._event = asyncio.Event()

    def request(self):
        self._event.set()

    def requested(self) -> bool:
        return self._event.is_set()

    async def wait(self):
        await self._event.wait()


async def cooperative_steps(token: CancelToken, steps: list[str], on_step):
    """每次可能产生副作用前检查取消信号。"""
    for step in steps:
        if token.requested():
            return "cancelled"
        await asyncio.sleep(0)
        await on_step(step)
    return "completed"


def request_cancel(status: str) -> str:
    if status in {"completed", "failed", "cancelled"}:
        return status
    if status in {"created", "running"}:
        return "cancelling"
    return status

