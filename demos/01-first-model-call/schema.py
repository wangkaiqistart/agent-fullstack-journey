"""修改计划契约：枚举、严格类型、额外字段与跨字段规则。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["edit", "ask_user", "finish"]
    # 字段必须出现，但值可以是 null，便于用于服务端严格 JSON Schema。
    file_path: str | None
    reason: str = Field(min_length=1, max_length=500)
    risk: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def check_business_fields(self):
        if not self.reason.strip():
            raise ValueError("reason 不能只有空白")
        if self.action == "edit" and not (self.file_path or "").strip():
            raise ValueError("edit 必须提供 file_path")
        if self.action == "finish" and self.file_path is not None:
            raise ValueError("finish 不应携带 file_path")
        return self


if __name__ == "__main__":
    # 查看真正发给模型服务的 Schema；这一步不调用模型。
    import json

    print(json.dumps(PatchPlan.model_json_schema(), ensure_ascii=False, indent=2))
