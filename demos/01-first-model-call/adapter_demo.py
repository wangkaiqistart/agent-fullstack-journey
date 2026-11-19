"""业务函数不变，分别注入 Chat 与 Responses 的真实 Adapter。"""

import argparse

from model_adapter import ChatCompletionsAdapter, ResponsesAdapter
from settings import create_client, run


def make_plan(model, task):
    # 业务层只依赖 generate() 和 ModelResult，不读取 choices / output。
    result = model.generate([{"role": "user", "content": task}])
    return f"{result.model}: {result.text}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alternate", action="store_true", help="Responses 使用另一套服务配置")
    args = parser.parse_args()
    for label, adapter_type, prefix in [
        ("Chat", ChatCompletionsAdapter, "AGENTOS_LLM"),
        ("Responses", ResponsesAdapter, "AGENTOS_ALT_LLM" if args.alternate else "AGENTOS_LLM"),
    ]:
        client, model = create_client(prefix=prefix)
        with client:
            print(label, make_plan(adapter_type(client, model), "用一句中文指出 def size(x): return len(x) 的风险。"))


if __name__ == "__main__":
    run(main)
