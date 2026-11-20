"""Gateway 管理的受控 Prompt 模板。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    required_variables: tuple[str, ...] = ()

    def render(self, variables: dict[str, str]) -> str:
        missing = [name for name in self.required_variables if not variables.get(name, "").strip()]
        if missing:
            raise ValueError("missing_prompt_variable:" + ",".join(missing))
        return self.system.format(**variables)


TEMPLATES = {
    ("kb-qa", "2.1"): PromptTemplate(
        name="kb-qa",
        version="2.1",
        system="你是企业知识库助手。只根据提供的资料回答；信息不足时明确说明。输出语言：{language}。",
        required_variables=("language",),
    )
}


def render_template(name: str, version: str | None, variables: dict[str, str]) -> PromptTemplate:
    if version is None:
        versions = [template for (template_name, _), template in TEMPLATES.items() if template_name == name]
        if not versions:
            raise ValueError("unknown_prompt_template:" + name)
        template = sorted(versions, key=lambda item: item.version)[-1]
    else:
        template = TEMPLATES.get((name, version))
        if template is None:
            raise ValueError(f"unknown_prompt_template:{name}@{version}")
    return template
