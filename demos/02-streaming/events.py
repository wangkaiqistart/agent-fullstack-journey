"""Harness 内部事件：模型流先归一化，再交给 Store 和 Gateway。"""

# datetime：日期时间类型；timezone：时区，这里用来获取 UTC（世界标准时间）
from datetime import datetime, timezone
# Any：任意类型；Literal：把取值限定为“几个固定的值”
from typing import Any, Literal

# pydantic：数据校验库。BaseModel 是模型基类，创建对象时会自动检查字段是否合法
# ConfigDict：模型的整体配置；Field：给单个字段加约束（如长度、范围、默认值）
from pydantic import BaseModel, ConfigDict, Field

# EventType：所有允许出现的事件类型。Literal 的作用是：写成列表之外的字符串会被校验拒绝
EventType = Literal[
    "run.started",      # 一次运行（run）开始
    "task.started",     # 运行中的某个任务开始
    "text.delta",       # 模型输出了一小段文字
    "tool.started",     # 开始调用某个工具（如搜索、查数据库）
    "tool.completed",   # 工具调用完成
    "model.finished",   # 模型这一轮输出结束
    "model.usage",      # token 用量统计
    "run.retrying",     # 运行出错，正在重试
    "run.completed",    # 运行成功结束
    "run.failed",       # 运行失败结束
    "run.cancelled",    # 运行被取消
]
# 终止事件：出现这三种之一，说明这次运行已经彻底结束，后面不会再有新事件
# 用 {} 是集合（set），判断“某个值是否在里面”时速度很快
TERMINAL_TYPES = {"run.completed", "run.failed", "run.cancelled"}


# 继承 BaseModel，创建 RunEvent 时 pydantic 会自动校验每个字段
class RunEvent(BaseModel):
    """可排序、去重、重放的业务事件。"""

    # extra="forbid"：不允许出现没定义的多余字段，防止拼写错误或脏数据悄悄混进来
    model_config = ConfigDict(extra="forbid")

    # 事件格式的版本号，固定为 "1"。以后格式变了可以升版本，方便新旧兼容
    schema_version: Literal["1"] = "1"
    # 这个事件属于哪一次运行；min_length=1 表示不能是空字符串
    run_id: str = Field(min_length=1)
    # 事件序号（sequence）：同一次运行内从 0 开始递增，ge=0 表示必须大于等于 0
    # 用途：排序；断线重连时客户端说“我收到第 5 号了”，服务端从第 6 号开始补发（重放）；重复收到同一序号则丢弃（去重）
    seq: int = Field(ge=0)
    # 事件类型，只能是上面 EventType 里列出的值
    type: EventType
    # 创建时间。default_factory 表示“每创建一个事件时才调用一次”，取当下的 UTC 时间
    # 如果直接写 default=datetime.now()，所有事件会共用程序启动时的同一个时间，这是常见的坑
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # 事件携带的内容，例如 {"delta": "你好"}；默认是空字典
    # 同样用 default_factory，保证每个事件各自拥有一个新字典，不会互相共享
    data: dict[str, Any] = Field(default_factory=dict)

    # @property：把方法变成“属性”，使用时写 event.terminal，不用加括号
    @property
    def terminal(self) -> bool:
        # 判断这个事件是不是终止事件
        return self.type in TERMINAL_TYPES
