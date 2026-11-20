"""修复失败后的安全结果：成功、只读缓存降级或失败。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from decision import AgentDecision


@dataclass(frozen=True)
class CachedDecision:
    task_key: str
    protocol_version: str
    expires_at: datetime
    decision: AgentDecision
    read_only: bool = True


@dataclass(frozen=True)
class FallbackResult:
    status: Literal["OK", "DEGRADED", "FAILED"]
    decision: AgentDecision | None
    reason: str


def choose_result(
    decision: AgentDecision | None,
    *,
    task_key: str,
    protocol_version: str,
    now: datetime | None = None,
    cache: CachedDecision | None = None,
) -> FallbackResult:
    """顺序固定为：修复成功 → 合格缓存 → 失败。"""
    if decision is not None:
        return FallbackResult("OK", decision, "模型输出通过校验")
    current = now or datetime.now(timezone.utc)
    if (
        cache
        and cache.read_only
        and cache.task_key == task_key
        and cache.protocol_version == protocol_version
        and cache.expires_at > current
    ):
        return FallbackResult("DEGRADED", cache.decision, "使用同一任务的近期只读缓存")
    return FallbackResult("FAILED", None, "没有可安全使用的决策")


def demo_cache(decision: AgentDecision) -> CachedDecision:
    return CachedDecision(
        task_key="expense-materials",
        protocol_version="1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        decision=decision,
    )
