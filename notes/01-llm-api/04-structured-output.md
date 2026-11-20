---
title: Structured Output：让 Agent 的输出可校验、可恢复、可执行
date: 2026-11-20
tags: [ai-agent, structured-output, json-schema, pydantic]
note_type: 技术笔记
learning_status: 未开始
---

# Structured Output：让 Agent 的输出可校验、可恢复、可执行

**Prompt 负责告诉模型“应该怎样决策”；Structured Output 和 Harness 负责确认“系统实际收到了什么决策”。**

配套代码：[demos/04-structured-output](../../demos/04-structured-output/README.md)。

## 阅读导航

| 主题 | 要回答的问题 |
| --- | --- |
| [1. 为什么不能直接用自然语言](#1-为什么不能直接用自然语言) | 为什么看起来正确的回答不能直接驱动程序？ |
| [2. JSON Schema](#2-json-schema) | 怎样声明字段、类型、必填项和枚举？ |
| [3. Pydantic 协议](#3-pydantic-协议) | 怎样让 Schema 和 Python 对象保持同一份定义？ |
| [4. 原生 Structured Output](#4-原生-structured-output) | API 层约束和本地校验怎样配合？ |
| [5. 三层校验](#5-三层校验) | 怎样区分格式、结构和业务错误？ |
| [6. 有限纠错](#6-有限纠错) | 哪些错误适合反喂模型？最多修复几次？ |
| [7. 降级与失败](#7-降级与失败) | 什么时候可以读缓存？什么时候必须失败？ |
| [8. 业务协议设计](#8-业务协议设计) | 怎样让输出真正服务于下游 Loop？ |
| [9. 实践](#9-实践) | 怎样验收非法输出不会触发工具？ |

## 1. 为什么不能直接用自然语言

模型返回的是文本；程序需要的是明确动作和字段。即使 Prompt 已经写了“请返回 JSON”，也不能把文本直接交给工具执行。

| 工程工作 | 必须决定什么 |
| --- | --- |
| 定义协议 | 允许哪些动作，每个动作需要哪些字段 |
| 实现校验 | 什么结果可以进入 Loop，什么结果必须拒绝 |
| 设计修复 | 哪些错误可以让模型重写，最多重写几次 |
| 处理失败 | 何时停止、何时降级、何时允许读取缓存 |

“像 JSON”不等于合法 JSON；合法 JSON 也不等于字段结构正确；字段结构正确还不等于业务上可执行。

## 2. JSON Schema

关键词解析脆弱且不可扩展：

```python
def parse_action(text: str) -> str:
    if "搜索" in text or "search_docs" in text:
        return "search_docs"
    return "finish"
```

这段代码无法可靠处理否定、同义表达、字段缺失、未知动作和跨字段关系。

JSON Schema 把协议写成机器可检查的声明：

```json
{
  "type": "object",
  "properties": {
    "action": {"type": "string", "enum": ["search_docs", "finish"]},
    "query": {"type": ["string", "null"]},
    "answer": {"type": ["string", "null"]}
  },
  "required": ["action", "query", "answer"],
  "additionalProperties": false
}
```

Schema 能明确字段名、类型、必填项、枚举范围和额外字段规则，但跨字段业务约束仍应在服务端再次校验。

## 3. Pydantic 协议

Pydantic 让同一个 Model 同时承担四项职责：

| 职责 | 在 Agent 中的作用 |
| --- | --- |
| 定义类型 | 明确 Loop 最终接收什么对象 |
| 生成 Schema | 把同一份结构提供给模型 API |
| 校验输出 | 拦截字段、类型和业务组合错误 |
| 反序列化 | 把 JSON 变成可直接使用的 Python 对象 |

```python
class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["search_docs", "finish"]
    query: str | None
    answer: str | None

    @model_validator(mode="after")
    def check_action_fields(self):
        if self.action == "search_docs" and not self.query:
            raise ValueError("search_docs 必须提供 query")
        if self.action == "finish" and not self.answer:
            raise ValueError("finish 必须提供 answer")
        return self
```

项目实现见 [decision.py](../../demos/04-structured-output/decision.py)。`model_json_schema()` 生成 Schema，`model_validate_json()` 同时完成解析、字段校验和对象构造。

## 4. 原生 Structured Output

三种输出约束是递进关系：

| 方式 | 能保证什么 | 不能保证什么 |
| --- | --- | --- |
| Prompt 要求 JSON | 模型知道期望格式 | 不保证 JSON、字段或业务规则 |
| JSON Mode | 主要保证合法 JSON | 不保证字段结构和跨字段关系 |
| 原生 Structured Output | API 层按 Schema 约束生成 | 仍需处理拒答、截断和业务语义 |

Chat Completions 示例：

```python
response = client.chat.completions.create(
    model=model,
    messages=messages,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "agent_decision",
            "strict": True,
            "schema": AgentDecision.model_json_schema(),
        },
    },
)
```

Responses 使用同一份 Schema，但字段位置是 `text.format`：

```python
response = client.responses.create(
    model=model,
    input=input_items,
    text={
        "format": {
            "type": "json_schema",
            "name": "agent_decision",
            "strict": True,
            "schema": AgentDecision.model_json_schema(),
        }
    },
)
```

完整链路是：

```text
模型生成候选 → API Schema 约束 → 本地 Pydantic 校验 → AgentDecision → Agent Loop
                                      ↓失败
                                  纠错或失败处理
```

原生约束减少格式错误，但不能让服务端校验代替业务校验；拒答、截断和不完整状态也不能进入 Loop。

## 5. 三层校验

一次校验依次覆盖三层边界：

| 层次 | 典型问题 | 结果 |
| --- | --- | --- |
| JSON 语法 | 引号或括号未闭合 | 无法解析 |
| 字段结构 | 字段缺失、类型错误、未知动作 | 无法构造对象 |
| 业务组合 | `finish` 没有答案，`search_docs` 没有查询 | 业务校验拒绝 |

全有或全无原则：

- `action` 缺失不能默认 `finish`；
- 未知字段不能静默删除后继续；
- 不能只取能解析的字段，把剩余错误留给工具；
- 只有完整通过校验的 `AgentDecision` 才能离开这一层。

项目的 [validation.py](../../demos/04-structured-output/validation.py) 保留错误层次，但对外只返回稳定的错误类别和简短位置，避免把内部堆栈直接推给客户端。

## 6. 有限纠错

第一次输出失败可能只是漏字段、类型错误或业务组合冲突。Pydantic 已经给出原因，Harness 可以把结构化反馈交给模型修正。

有效反馈必须说明：

1. 哪里错了；
2. 为什么错了；
3. 允许修改什么。

修复循环只重新生成决策，不执行任何工具。比如最多修复两次：

```python
result, repair_count = repair_until_valid(
    first_raw,
    repair_model,
    max_repairs=2,
)
```

| 失败类型 | 处理方式 |
| --- | --- |
| 字段缺失、类型错误、组合冲突 | 反馈校验错误，让模型修复 |
| 网络超时、限流 | 模型调用层按退避策略重试 |
| 权限不足 | 立即拒绝或请求授权 |
| 知识库不可用 | 停止、切换服务或转人工 |

不要把所有异常都反喂 Prompt；不同错误需要由不同层处理。

## 7. 降级与失败

多次修复仍失败时，结果只有三类：

| 状态 | 含义 |
| --- | --- |
| `OK` | 模型给出合法决策，可以进入 Loop |
| `DEGRADED` | 模型失败，但找到满足条件的替代结果 |
| `FAILED` | 没有任何结果可以安全使用，`decision = None` |

安全顺序：

```text
有限修复 → 合法决策 → 合格缓存 → FAILED
```

缓存不是“出错后随便找一条旧答案”。只有同一任务的近期只读结果，并且同时满足以下条件，才允许降级：

- 任务键一致；
- 协议版本一致；
- 仍在有效期内；
- 结果不会触发不可逆副作用。

项目实现见 [fallback.py](../../demos/04-structured-output/fallback.py)。找不到合格缓存时必须失败，不能猜测动作或团队后继续执行。

## 8. 业务协议设计

设计 Schema 前先回答五个问题：

1. 谁消费输出？
2. 输出决定什么？
3. 允许哪些动作？
4. 每种动作需要哪些数据？
5. 失败后怎样处理？

字段不需要复杂。`action`、`query`、`answer` 已经可以表达一个知识库路由决策；没有被程序使用的字段只会增加误用和维护成本。

课堂练习可以换成工单分类 Agent：

- `action` 只能是 `route_to_team` 或 `ask_user`；
- 转交时必须有 `team`；
- 追问时必须有 `question`；
- 禁止额外字段；
- 最多修复两次；
- 连续失败返回 `failed`，不能猜测团队继续执行。

## 9. 实践

先运行：

```bash
.venv/bin/python demos/04-structured-output/structured_output.py
.venv/bin/python demos/04-structured-output/responses_structured_output.py
.venv/bin/python demos/04-structured-output/repair_demo.py
.venv/bin/python -m unittest discover -s demos/04-structured-output/tests -v
```

改变问题，观察模型选择 `search_docs` 还是 `finish`；再把本地校验中的字段删除、枚举改错、加入额外字段，确认所有非法结果都被拒绝。

验收标准：

- Schema 来自 Pydantic，而不是手写第二份规则；
- 合法 JSON、结构合法和业务可执行被分别验证；
- 修复次数有上限；
- 修复阶段不执行工具；
- 连续失败返回明确的降级或失败状态；
- 非法输出永远不会产生工具副作用。

## 示例索引

| 能力 | 代码 | 方式 |
| --- | --- | --- |
| 业务协议与 Schema | [decision.py](../../demos/04-structured-output/decision.py) | 本地 |
| 三层错误校验 | [validation.py](../../demos/04-structured-output/validation.py) | 本地 |
| Chat 原生约束 | [structured_output.py](../../demos/04-structured-output/structured_output.py) | 真实模型 |
| Responses 原生约束 | [responses_structured_output.py](../../demos/04-structured-output/responses_structured_output.py) | 真实模型 |
| 有限纠错 | [repair_loop.py](../../demos/04-structured-output/repair_loop.py) | 本地可注入模型 |
| 缓存降级 | [fallback.py](../../demos/04-structured-output/fallback.py) | 本地 |
| 离线演示 | [repair_demo.py](../../demos/04-structured-output/repair_demo.py) | 本地 |
| 边界测试 | [tests/test_structured_output.py](../../demos/04-structured-output/tests/test_structured_output.py) | 本地 |

## 验证记录

2026-11-20，使用项目 `.venv` 和当前模型配置完成 4 项本地协议测试。Chat Completions 与 Responses 两个真实入口均成功返回 `search_docs` 决策，`query` 为非空字符串，`answer` 为 `null`，随后通过本地 Pydantic 校验。示例不会执行搜索、写入或其他工具副作用。

个人学习状态为 `未开始`。运行成功只证明链路可用；需要独立修改 Schema、制造非法候选、改变修复次数和缓存条件，再解释每个结果为什么被接受或拒绝。

