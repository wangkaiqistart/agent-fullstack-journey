"""可重放的内存 Run Store；生产环境可替换为 PostgreSQL + Redis 通知。"""

from dataclasses import dataclass, field
# RLock：可重入锁。同一个线程可以重复加锁而不会死锁
# （publish 持有锁时又调用 get，get 里还要再加一次锁，普通 Lock 会卡死）
from threading import RLock
# uuid4：生成随机唯一 ID
from uuid import uuid4

from events import RunEvent


@dataclass
class RunState:
    """一次运行的全部状态。"""

    run_id: str
    # 状态：created（已创建）→ running（运行中）→ completed / failed / cancelled（终态）
    # 另有 cancelling：已请求取消，但还没真正停下来
    status: str = "created"
    # 这次运行产生的所有事件，按 seq 顺序排列；断线重放就是从这里取
    # 用 default_factory 保证每个 RunState 各有一个新列表，不会共用
    events: list[RunEvent] = field(default_factory=list)
    # 是否有人请求过取消。Agent Loop 每处理一个模型事件就检查它（协作式取消）
    cancel_requested: bool = False


class InMemoryRunStore:
    """把所有运行保存在内存字典里：重启就丢失，只适合学习和测试。"""

    def __init__(self):
        self._runs: dict[str, RunState] = {}  # run_id → 运行状态
        self._lock = RLock()  # 保护上面的字典和事件列表，避免多线程同时修改

    def create(self) -> str:
        """创建一次新运行，返回 run_id。"""
        with self._lock:  # with：进入时加锁，离开时自动解锁
            # "run_" 加上 12 位随机十六进制字符，例如 run_e16a1e50bf51
            run_id = "run_" + uuid4().hex[:12]
            self._runs[run_id] = RunState(run_id)
            return run_id

    def get(self, run_id: str) -> RunState:
        """按 ID 取运行状态；不存在时抛出 KeyError。"""
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            # 注意：返回的是内部对象本身，不是副本。离开这个函数后锁就释放了，
            # 调用方拿着它读取是安全的，但不应该直接修改
            return self._runs[run_id]

    def publish(self, run_id: str, event_type: str, data: dict | None = None) -> RunEvent:
        """发布一个事件：分配 seq、追加到列表、更新状态。这是本类最核心的方法。"""
        with self._lock:  # 整个过程加锁，保证“取序号 + 追加”是一个不可拆分的动作
            state = self.get(run_id)
            # 已经有终态事件，就拒绝再追加：一个运行只能有一个终态
            if state.events and state.events[-1].terminal:
                raise ValueError("终态后不能继续发布事件")
            # seq 直接取当前事件数量：第一个事件是 0，第二个是 1……
            # 能这样做的前提就是上面的锁，否则两个线程可能拿到同一个序号
            # 先创建事件再追加：如果 event_type 不合法，pydantic 会在这里报错，列表不会被污染
            event = RunEvent(run_id=run_id, seq=len(state.events), type=event_type, data=data or {})
            state.events.append(event)
            # 根据事件类型更新运行状态
            if event_type == "run.started":
                # 如果启动前就有人请求取消，直接进入 cancelling，而不是 running
                state.status = "cancelling" if state.cancel_requested else "running"
            elif event_type == "run.cancelled":
                state.status = "cancelled"
            elif event_type == "run.completed":
                state.status = "completed"
            elif event_type == "run.failed":
                state.status = "failed"
            # 其他事件（text.delta 等）不改变状态
            return event

    def list_after(self, run_id: str, last_seq: int = -1) -> list[RunEvent]:
        """返回 seq 大于 last_seq 的所有事件。断线重连和重放就靠它。"""
        # 默认 -1：所有 seq 都 ≥ 0，所以会返回全部事件
        state = self.get(run_id)
        return [event for event in state.events if event.seq > last_seq]

    def request_cancel(self, run_id: str) -> bool:
        """请求取消。返回 True 表示请求被接受，False 表示运行已经结束、无需取消。"""
        with self._lock:
            state = self.get(run_id)
            # 已经是终态：取消没有意义，拒绝
            if state.status in {"completed", "failed", "cancelled"}:
                return False
            # 只是记录“有人想取消”，不会立刻停止；真正停下来由 Agent Loop 发现标记后处理
            state.cancel_requested = True
            if state.status in {"created", "running"}:
                state.status = "cancelling"
            # 重复请求取消也返回 True（幂等：多次调用和一次的效果相同）
            return True

    def is_cancel_requested(self, run_id: str) -> bool:
        """Agent Loop 用来检查是否被要求取消。"""
        return self.get(run_id).cancel_requested
