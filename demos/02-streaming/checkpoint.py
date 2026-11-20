"""长任务检查点：保存可恢复状态，不把半成品当成可执行结果。"""

import json
# Path：用面向对象的方式处理文件路径
from pathlib import Path
# Any：任意类型
from typing import Any

# BaseModel：数据模型基类，创建对象时自动校验字段；ConfigDict：模型配置；Field：给字段加约束
from pydantic import BaseModel, ConfigDict, Field


class Checkpoint(BaseModel):
    """检查点：记录“做到哪一步了”，进程崩溃后可以从这里继续，而不是从头再来。"""

    # extra="forbid"：不允许出现没定义的多余字段，防止拼写错误或脏数据混进来
    model_config = ConfigDict(extra="forbid")

    # 检查点格式的版本号；ge=1 表示必须大于等于 1。以后格式变了可以升版本，方便兼容
    version: int = Field(ge=1)
    # 属于哪一次运行
    run_id: str
    # 循环执行到哪个阶段，例如 "tool" 表示正在调用工具
    loop_step: str
    # 已经完成的步骤，例如 ["search"]。default_factory=list：每个对象各自新建一个空列表，不共用
    completed: list[str] = Field(default_factory=list)
    # 下一步从哪里继续（cursor 意为“游标”，指向下一个位置）；None 表示没有
    next_cursor: str | None = None
    # 上下文的摘要值（如 "sha256:..."）。恢复时核对上下文有没有变，避免拿旧状态接上新内容
    context_digest: str
    # 每个工具调用的状态，例如 {"call_id": "c1", "sent": True} 表示这个调用已经发出
    # 恢复时靠它避免重复调用有副作用的工具（如重复扣款、重复发邮件）
    tool_state: list[dict[str, Any]] = Field(default_factory=list)


def save_checkpoint(path: Path, checkpoint: Checkpoint) -> None:
    """把检查点写成 JSON 文件。"""
    # parents=True：上级目录不存在时一并创建；exist_ok=True：目录已存在也不报错
    path.parent.mkdir(parents=True, exist_ok=True)
    # model_dump_json(indent=2)：转成缩进 2 个空格的 JSON 文本，方便人阅读；末尾补一个换行
    path.write_text(checkpoint.model_dump_json(indent=2) + "\n")


def load_checkpoint(path: Path) -> Checkpoint:
    """从 JSON 文件读回检查点。"""
    # model_validate_json：读出文本后重新校验；文件被改坏或缺字段会直接报错，
    # 不会把半成品当成可用状态
    return Checkpoint.model_validate_json(path.read_text())
