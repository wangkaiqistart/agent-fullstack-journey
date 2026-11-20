"""有限纠错：只修复候选决策，不在纠错阶段执行工具。"""

from collections.abc import Callable

from validation import ValidationResult, validate_json


def repair_until_valid(
    first_raw: str,
    repair: Callable[[str], str],
    *,
    max_repairs: int = 2,
) -> tuple[ValidationResult, int]:
    """返回合法决策或最后一次失败；修复次数有硬上限。"""
    if max_repairs < 0:
        raise ValueError("max_repairs 不能为负数")
    raw = first_raw
    for repair_count in range(max_repairs + 1):
        result = validate_json(raw)
        if result.ok or repair_count == max_repairs:
            return result, repair_count
        feedback = result.message or "输出未通过校验"
        raw = repair(f"哪里错了：{feedback}\n为什么错了：输出不能进入 Agent Loop。\n允许修改：只修复 JSON 字段和业务组合。")
    raise AssertionError("循环应在上限内返回")
