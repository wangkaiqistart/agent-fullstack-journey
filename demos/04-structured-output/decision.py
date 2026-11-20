"""Agent 决策协议：字段、枚举和跨字段业务规则。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentDecision(BaseModel):
    """只有通过本地业务校验的对象才允许进入 Agent Loop。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["search_docs", "finish"]
    query: str | None
    answer: str | None

    @model_validator(mode="after")
    def check_action_fields(self):
        if self.action == "search_docs":
            if not self.query or not self.query.strip():
                raise ValueError("search_docs 必须提供 query")
            if self.answer is not None:
                raise ValueError("search_docs 不应提前提供 answer")
        if self.action == "finish":
            if not self.answer or not self.answer.strip():
                raise ValueError("finish 必须提供 answer")
            if self.query is not None:
                raise ValueError("finish 不应携带 query")
        return self


def schema() -> dict:
    """导出给模型 API 的同一份 JSON Schema。"""
    return AgentDecision.model_json_schema()


if __name__ == "__main__":
    import json

    print(json.dumps(schema(), ensure_ascii=False, indent=2))
    raw_schema = """
    {
    "action": "search_docs",
    "query": "123",
    "answer": null
    }
    """
    decision = AgentDecision.model_validate_json(raw_schema)
    print(decision.action)
    print(decision.query)
    print(decision.answer)
