"""Gateway 出口使用的最小业务 Schema；与上游协议隔离。"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["search_docs", "finish"]
    query: str | None
    answer: str | None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "search_docs" and (not self.query or self.answer is not None):
            raise ValueError("search_docs 需要 query 且不能提前提供 answer")
        if self.action == "finish" and (not self.answer or self.query is not None):
            raise ValueError("finish 需要 answer 且不能携带 query")
        return self


def validate_agent_decision(raw: str) -> AgentDecision:
    json.loads(raw)  # 先区分 JSON 语法错误，再做字段与业务校验。
    return AgentDecision.model_validate_json(raw)
