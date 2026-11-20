"""真实模型示例：把代码审查拆成分析、执行、检查三步。"""

import argparse

from settings import create_client, run


def ask(client, model, instruction: str) -> str:
    response = client.chat.completions.create(
        model=model,
        # 把稳定职责放在 System，把本次步骤放在 User，避免把所有内容混成一条规则。
        messages=[
            {"role": "system", "content": "你是一个只根据输入证据工作的代码审查助手。"},
            {"role": "user", "content": instruction},
        ],
        max_completion_tokens=512,
    )
    if not response.choices:
        raise ValueError("响应中没有 choices")
    choice = response.choices[0]
    if choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError(f"步骤未正常完成：finish_reason={choice.finish_reason}")
    return choice.message.content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="def size(x): return len(x)")
    args = parser.parse_args()
    client, model = create_client()
    code = f"<untrusted_code>\n{args.code}\n</untrusted_code>"
    with client:
        analysis = ask(client, model, f"""
你是代码审查流程的分析阶段。
只提取目标、约束、已有证据和缺失信息，不给最终修复建议，不执行代码。
{code}
输出四个短小栏目：目标、约束、证据、缺失信息。
""")
        execution = ask(client, model, f"""
你是代码审查流程的执行阶段。
根据原始代码和分析结果，列出可由代码证据支持的问题、位置、原因和建议。
不要声称已经运行或修改代码；没有证据就写无法确认。
原始代码：
{code}
分析结果：
<analysis>{analysis}</analysis>
""")
        checked = ask(client, model, f"""
你是代码审查流程的检查阶段。
对照原始代码和原始目标，检查下面的审查结果是否偏题、遗漏或包含猜测。
只输出修订后的最终审查结果，先给结论，再给风险、证据和建议。
原始代码：
{code}
分析结果：
<analysis>{analysis}</analysis>
执行结果：
<execution>{execution}</execution>
""")
    print("[分析]\n" + analysis)
    print("\n[执行]\n" + execution)
    print("\n[检查后的结果]\n" + checked)


if __name__ == "__main__":
    run(main)
