"""把 JSON 语法、字段结构和业务组合错误分层诊断。"""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from decision import AgentDecision


@dataclass(frozen=True)
class ValidationResult:
    decision: AgentDecision | None
    error_kind: str | None
    message: str | None

    @property
    def ok(self) -> bool:
        return self.decision is not None


def validate_json(raw: str) -> ValidationResult:
    """全有或全无：失败时不返回部分字段，也不猜默认动作。"""
    try:
        json.loads(raw)
    except json.JSONDecodeError as error:
        return ValidationResult(None, "json_syntax", f"JSON 语法错误：第 {error.pos} 个字符")
    try:
        decision = AgentDecision.model_validate_json(raw)
    except ValidationError as error:
        # 对外只返回稳定类别和简短原因；详细异常留在服务端日志。
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "root"
        return ValidationResult(None, "schema_or_business", f"字段 {location} 未通过校验")
    return ValidationResult(decision, None, None)

if __name__ == '__main__':
    str = """{
    "action": "search_docs",
    "query": "123",
    "answer": null
    }
    """
    print(validate_json(str))