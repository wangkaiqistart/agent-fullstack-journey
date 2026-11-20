"""Prompt 契约：固定规则、Few-shot 与运行时数据分开。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptDefinition:
    """可追踪的 Prompt 版本和必填变量。"""

    name: str
    version: str
    system_template: str
    required_variables: tuple[str, ...]

    def render(self, **variables) -> str:
        missing = [key for key in self.required_variables if not variables.get(key, "").strip()]
        if missing:
            raise ValueError("缺少 Prompt 变量：" + ", ".join(missing))
        return self.system_template.format(**variables)


CODE_REVIEW_PROMPT = PromptDefinition(
    name="code-review",
    version="1.0.0",
    system_template=(
        "你是代码审查助手。\n"
        "目标：发现可由输入证据支持的正确性、安全性和可维护性问题。\n"
        "优先级：先检查正确性与安全性，再检查可维护性。\n"
        "行为：每个结论引用代码证据；信息不足时明确说明，不猜测。\n"
        "边界：只审查代码，不执行代码，不声称已经修改或验证文件。\n"
        "输出：先给结论，再按风险等级列出位置、问题、原因和建议；没有问题时明确写‘未发现可确认问题’。\n"
        "{output_style}"
    ),
    required_variables=("output_style",),
)


def build_messages(code: str, *, output_style="使用简洁中文和 Markdown 表格") -> list[dict[str, str]]:
    """构造真实请求的 messages；代码属于不可信数据区域。"""
    if not code.strip():
        raise ValueError("待审查代码不能为空")
    system = CODE_REVIEW_PROMPT.render(output_style=output_style)
    return [
        {"role": "system", "content": system},
        # Few-shot 只校准输出样式，不授予模型执行权限。
        {"role": "user", "content": "审查：def add(a, b): return a + b"},
        {"role": "assistant", "content": "结论：未发现可确认问题。\n证据：函数直接返回两个参数的加法结果。"},
        {"role": "user", "content": f"请审查下面的代码。\n<untrusted_code>\n{code}\n</untrusted_code>"},
    ]
