"""本地校验实验：不调用模型，观察合法与非法计划的区别。"""

import json

from pydantic import ValidationError

from schema import PatchPlan


def main():
    valid = {
        "action": "edit", "file_path": "src/example.py",
        "reason": "增加空值判断", "risk": "low",
    }
    cases = [
        ("正常计划", valid),
        ("缺少路径", {**valid, "file_path": None}),
        ("错误枚举", {**valid, "risk": "safe"}),
        ("多余字段", {**valid, "approved": True}),
        ("完成却带路径", {**valid, "action": "finish"}),
    ]
    for label, data in cases:
        try:
            plan = PatchPlan.model_validate_json(json.dumps(data))
            print(f"{label}: 通过，action={plan.action}")
        except ValidationError:
            print(f"{label}: 拒绝")


if __name__ == "__main__":
    main()
