# Structured Output Demo

把模型看起来像 JSON 的文本，变成可以安全进入 Agent Loop 的业务协议。

配套笔记：[Structured Output：让 Agent 的输出可校验、可恢复、可执行](../../notes/01-llm-api/04-structured-output.md)。

## 目标

- 用 Pydantic 定义字段、类型、枚举和跨字段规则。
- 从同一个 Model 生成 JSON Schema，并把 Schema 交给模型 API。
- 区分 JSON 语法、字段结构和业务组合错误。
- 只在有限次数内修复候选决策，不在修复阶段执行工具。
- 连续失败后只使用同任务、同协议、未过期的只读缓存，否则返回 `FAILED`。

## 环境

要求 Python 3.11+、仓库根目录 `.venv` 和 OpenAI Compatible 服务。依赖复用根目录固定版本：

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

真实调用读取根目录 `.env`：

```dotenv
AGENTOS_LLM_BASE_URL=https://example.invalid/v1
AGENTOS_LLM_API_KEY=
AGENTOS_LLM_MODEL=gpt-5.6-luna
```

## 示例入口

| 文件 | 作用 | 方式 |
| --- | --- | --- |
| [decision.py](decision.py) | AgentDecision 协议与 JSON Schema | 本地 |
| [validation.py](validation.py) | 三层校验与错误分类 | 本地 |
| [structured_output.py](structured_output.py) | Chat Completions 原生 Schema | 真实模型 |
| [responses_structured_output.py](responses_structured_output.py) | Responses `text.format` Schema | 真实模型 |
| [repair_loop.py](repair_loop.py) | 有次数上限的纠错 | 本地可注入模型 |
| [fallback.py](fallback.py) | 成功、缓存降级、失败 | 本地 |
| [repair_demo.py](repair_demo.py) | 修复和降级演示 | 本地 |
| [tests/test_structured_output.py](tests/test_structured_output.py) | 协议边界测试 | 本地 |

## 三层校验

```text
模型候选
  ↓
JSON 语法        引号、括号、合法 JSON
  ↓
字段结构        类型、必填项、枚举、额外字段
  ↓
业务组合        action 与 query / answer 的关系
  ↓
AgentDecision   才允许进入 Loop
```

全有或全无：校验失败时不默认 `finish`，不删除未知字段后继续，也不把部分字段交给工具。

## 真实模型调用

### Chat Completions

```bash
.venv/bin/python demos/04-structured-output/structured_output.py
.venv/bin/python demos/04-structured-output/structured_output.py \
  --question "我已经知道报销材料，直接给出答案。"
```

请求使用 `response_format.type=json_schema`，模型返回后仍调用 `AgentDecision.model_validate_json()`。原生约束减少格式错误，但不能代替本地业务校验。

### Responses

```bash
.venv/bin/python demos/04-structured-output/responses_structured_output.py
```

Responses 使用 `text.format` 传递同一份 Schema；两种 API 最终都汇聚到同一个 `AgentDecision` 和同一套本地校验。

## 有限纠错与降级

```bash
# 本地模拟：一次修复成功；连续失败后使用合格只读缓存。
.venv/bin/python demos/04-structured-output/repair_demo.py

# 运行协议、错误分类、纠错上限和缓存边界测试。
.venv/bin/python -m unittest discover -s demos/04-structured-output/tests -v
```

只有字段缺失、类型错误和业务组合冲突适合反馈给模型。网络超时、限流、权限不足和知识库不可用应由对应层处理，不能把所有错误都塞回 Prompt。

降级顺序固定为：

```text
有限修复 → 合法决策 → 合格缓存 → FAILED
```

缓存必须同时满足任务键、协议版本、有效期和只读条件；缓存不是出错后随便取的一条旧答案。

## 本地验证

```bash
python3 -m compileall -q demos/04-structured-output
.venv/bin/python -m unittest discover -s demos/04-structured-output/tests -v
```

离线测试覆盖：额外字段拒绝、枚举错误、跨字段冲突、JSON 语法错误、纠错次数上限、同任务同协议缓存和缓存过期边界。测试替身不代表模型真实遵守 Schema。

2026-11-20 已用当前配置真实运行 Chat Completions 和 Responses 两个入口：两者都返回合法的 `search_docs` 决策，并通过本地 Pydantic 校验；没有执行搜索工具。

## 工具执行边界

本 Demo 只打印决策，不执行搜索工具。真实 Agent 必须在 `AgentDecision` 通过本地校验后再根据 `action` 分派工具；拒答、截断、解析失败、业务校验失败和连续修复失败都不能触发工具副作用。

