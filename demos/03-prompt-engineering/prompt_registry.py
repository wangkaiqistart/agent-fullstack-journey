"""本地 Prompt 注册表：变量校验、版本标识和变更记录。"""

from dataclasses import dataclass

from prompt_contract import CODE_REVIEW_PROMPT


@dataclass(frozen=True)
class Change:
    version: str
    summary: str


CHANGES = (
    Change("1.0.0", "定义代码审查角色、边界和基本输出结构"),
    Change("1.1.0", "加入 Few-shot 和不可信代码区域"),
)


def get_prompt(name: str):
    """按名称获取当前版本；不存在时快速失败。"""
    if name != CODE_REVIEW_PROMPT.name:
        raise KeyError(f"未知 Prompt：{name}")
    return CODE_REVIEW_PROMPT


def main():
    prompt = get_prompt("code-review")
    print(f"name={prompt.name}")
    print(f"version={prompt.version}")
    print("required_variables=" + ",".join(prompt.required_variables))
    print("changes:")
    for change in CHANGES:
        print(f"- {change.version}: {change.summary}")


if __name__ == "__main__":
    main()
