---
title: 阶段一：LLM 统一模型调用服务
date: 2026-11-20
tags: [ai-agent, llm-gateway, project, openai-compatible]
note_type: 阶段项目
learning_status: 未开始
---

# 阶段一：LLM 统一模型调用服务

**前面几节验证了模型调用的核心语义；阶段项目要把这些语义迁移成可配置、可部署、可治理的服务。**

项目代码：[projects/01-llm-gateway](../../projects/01-llm-gateway/README.md)。概念拆解：[demos/05-llm-gateway](../../demos/05-llm-gateway/README.md)。

## 阅读导航

| 主题 | 要回答的问题 |
| --- | --- |
| [1. 从原型到服务](#1-从原型到服务) | 1.6 的单文件原型还缺什么？ |
| [2. 内部领域协议](#2-内部领域协议) | 为什么外部兼容接口不能直接当内部模型？ |
| [3. OpenAI Compatible API](#3-openai-compatible-api) | 怎样让已有 SDK 接入而不暴露供应商？ |
| [4. 能力路由](#4-能力路由) | 怎样按能力、优先级和健康状态选模型？ |
| [5. 统一三种输出](#5-统一三种输出) | 普通、Streaming 和 Structured Output 怎样共用边界？ |
| [6. Prompt Bundle](#6-prompt-bundle) | 一个可发布 Prompt 版本包含什么？ |
| [7. 弹性与资源边界](#7-弹性与资源边界) | 怎样控制重试、限流、熔断和成本？ |
| [8. 接入 Agent Harness](#8-接入-agent-harness) | Gateway 和 Loop 的责任怎样分开？ |
| [9. 测试与验收](#9-测试与验收) | 怎样证明服务真的可治理？ |

## 1. 从原型到服务

1.6 的原型已经验证了消息协议、Provider Adapter、Structured Output、主备切换和 SSE，但单文件里仍可能混有供应商地址、密钥、响应结构和业务编排。

阶段项目要把调用链拆成：

```text
Web / CLI / Agent Loop
          ↓ OpenAI Compatible API
API Layer → Auth / Rate Limit → Prompt → Router
          → Provider Adapter → Schema / Usage
          → Trace / Metrics / Cost Ledger
```

升级目标：

- 供应商配置从 Python 常量移到 YAML；
- 上层使用逻辑模型名，不直接绑定供应商模型；
- 普通、流式和结构化请求共用编排链；
- 调用、路由、重试、成本和错误可以追踪；
- 服务可以独立启动、检查和测试。

## 2. 内部领域协议

OpenAI Compatible 是外部接入协议，不是内部领域模型。外部协议应在 API Layer 终止，Gateway 内部使用自己的请求、结果和错误模型。

### 请求应该保留什么

- `requested_model`：调用方请求的逻辑模型名；
- `messages`：平台消息协议；
- `stream`：是否请求增量输出；
- `response_format`：结构化输出要求；
- 输出预算和平台级选项。

### 结果应该保留什么

- `requested_model`；
- `resolved_model`：实际解析到的模型；
- Provider 名称；
- 统一文本、Usage、结束原因和错误码；
- `trace_id`、尝试次数和 fallback 标志。

`requested_model` 和 `resolved_model` 必须同时记录，否则无法解释一次路由到底用了谁。

## 3. OpenAI Compatible API

FastAPI 对外提供兼容接口，已有 OpenAI SDK 可以改变 `base_url` 后接入；供应商密钥只存在 Gateway 配置中。

阶段项目提供：

| 接口 | 作用 |
| --- | --- |
| `POST /v1/chat/completions` | 普通完整响应或 SSE 流式响应 |
| `GET /healthz` | 进程存活 |
| `GET /readyz` | 是否至少加载一个 Provider |
| `GET /admin/providers` | 查看 Provider 能力，不返回密钥 |
| `GET /admin/usage` | 查询本地用量记录 |

上层只提交：

```json
{
  "model": "default",
  "messages": [{"role": "user", "content": "解释 Gateway"}],
  "stream": false
}
```

上层不提交真实 Base URL、API Key、供应商响应类型或任意重试参数。

## 4. 能力路由

路由不是“挑最强模型”，而是根据能力声明、优先级、成本和健康状态选择候选。

每个 Provider 注册能力，例如：

```yaml
capabilities: [chat, streaming, structured_output]
```

逻辑模型名映射候选 Provider：

```yaml
models:
  default:
    providers: [primary, backup]
    required_capabilities: [chat]
```

路由过程：

1. 根据逻辑模型名找到候选列表；
2. 过滤不满足能力的 Provider；
3. 按优先级和健康状态排序；
4. 记录候选和拒绝原因；
5. 在首个内容块前执行有限重试或 fallback。

路由决策必须可以被 Eval 回放和解释，不能只保存最终模型名。

## 5. 统一三种输出

### 普通调用

```text
同步请求 → Provider → 完整响应 → 统一结果
```

这是最简单的链路，也是重试和 fallback 的基准。

### Streaming

Gateway 内部维护统一事件：

```text
delta → tool_call → usage → done / failed / cancelled
```

对外使用 SSE。首个 delta 前可以有限重试；已经发送后发生错误，只能结束或发送失败事件，不能换模型拼接。

### Structured Output

有两层保证：

1. 请求时把 JSON Schema 传给 Provider；
2. 返回后在 Gateway 使用 Pydantic 再校验。

供应商的 Schema 保证不等于应用层安全。合法 JSON 也可能不满足业务组合规则。

流式 JSON 还需要增量解析；部分 JSON 不能提前做完整 Schema 校验，最终结果必须在流结束后再次校验。

## 6. Prompt Bundle

一个可发布的 Prompt 版本不只是 System Prompt 文本，至少包含：

- System Prompt 模板；
- 输入变量 Schema；
- Few-shot 示例；
- 输出 JSON Schema；
- 工具定义版本；
- 默认逻辑模型和生成参数；
- Context 预算；
- Eval 集和通过门槛；
- 变更说明和发布状态。

模板渲染必须受限：

- 只支持变量替换和有限条件分支；
- 不使用 `eval` 或 `exec`；
- 渲染前校验变量缺失、长度和内容边界；
- 每次调用记录 Prompt 名称、版本和 hash；
- 不可信变量不能无条件进入 System Prompt。

项目当前实现了 YAML 配置和基础变量替换；模板 Bundle 的完整 Eval 门槛和 hash 记录是后续扩展项。

## 7. 弹性与资源边界

不同阶段的错误不能使用同一种策略：

| 阶段 | 例子 | 处理 |
| --- | --- | --- |
| 认证 | API Key 无效、租户禁用 | 不重试 |
| 请求校验 | 参数非法、Schema 缺失 | 修正请求后再试 |
| Prompt | 缺变量、超过预算 | 拒绝并返回错误码 |
| 路由 | 没有兼容模型 | 配置变化后再试 |
| 排队 | 并发已满、截止时间不足 | 拒绝或换池 |
| 连接 | 网络抖动、短暂 5xx | 有上限重试 |
| 首 Token 前 | 429、超时、过载 | 有限重试或 fallback |
| 已输出后 | 连接中断 | 不盲目重新生成 |
| 输出校验 | JSON / Schema 错误 | 有限修复 |
| 内容拒答 | 安全策略拒绝 | 不换模型绕过 |

资源治理还需要：

- 指数退避和 jitter；
- 并发上限，不能只限制 QPS；
- 总超时和输出预算；
- 熔断和恢复窗口；
- Idempotency-Key 处理请求重放。

幂等键可以避免业务层重复创建任务，但不一定能避免供应商已经发生的重复计费。

## 8. 接入 Agent Harness

Loop 只依赖 Gateway 的模型端口：

```text
Agent Loop
  ├─ 工具调用
  ├─ 循环控制
  ├─ Run / Step 状态
  └─ 业务终态
          ↓ 统一模型接口
LLM Gateway
  ├─ Provider 执行
  ├─ 路由与 fallback
  ├─ Prompt / Schema
  ├─ Token / Cost / Latency
  └─ 调用 Trace
```

一次 Loop Step 可能包含多次模型调用：

```text
run_id → step_id → call_id → trace_id
```

Gateway 记录每个 `call_id` 的路由、Token、成本和错误；Harness 记录 Step、工具权限和任务终态。两层 Trace 通过 `run_id` 和 `step_id` 关联。

Gateway 返回模型执行结果，不负责判断业务任务是否完成。

## 9. 测试与验收

阶段项目测试不只看 HTTP 200：

| 测试 | 验证 |
| --- | --- |
| Adapter Contract | 请求翻译、响应翻译和错误映射 |
| Router | 能力匹配、优先级、fallback、拒绝原因 |
| Retry | 超时和错误次数，不真实等待 |
| Streaming | delta 顺序、usage、终态和错误中断 |
| Structured Output | JSON、Schema、修复上限和错误返回 |
| Observability | Trace、Metrics、Cost Ledger 关键字段 |

必须保持三条不变量：

1. 未通过 Schema 的输出不能进入 Agent Loop；
2. 流已经输出首块以后不能切换模型重新生成；
3. 无论使用主模型还是备用模型，上层都只依赖同一份请求、响应和错误协议。

### 当前项目验收

```bash
.venv/bin/python -m unittest discover -s projects/01-llm-gateway/tests -v
python3 -m compileall -q projects/01-llm-gateway
```

已覆盖：逻辑模型未知、能力路由、主模型重试后备用模型、流式增量、Usage SQLite 记录。真实服务启动后还应手工验证 `/healthz`、`/readyz`、`/v1/chat/completions` 和 SSE 输出。

## 示例索引

| 能力 | 代码 | 方式 |
| --- | --- | --- |
| 阶段项目说明 | [projects/01-llm-gateway/README.md](../../projects/01-llm-gateway/README.md) | 服务入口 |
| YAML 配置 | [gateway.example.yaml](../../projects/01-llm-gateway/gateway.example.yaml) | 配置 |
| OpenAI Compatible 协议 | [schemas.py](../../projects/01-llm-gateway/app/schemas.py) | 本地 |
| Provider Adapter | [providers.py](../../projects/01-llm-gateway/app/providers.py) | 真实入口 |
| 模型路由 | [router.py](../../projects/01-llm-gateway/app/router.py) | 本地 |
| Gateway 编排 | [gateway.py](../../projects/01-llm-gateway/app/gateway.py) | 本地 + 真实入口 |
| SQLite 用量 | [usage.py](../../projects/01-llm-gateway/app/usage.py) | 本地 |
| FastAPI 服务 | [main.py](../../projects/01-llm-gateway/app/main.py) | FastAPI |
| 阶段测试 | [test_gateway.py](../../projects/01-llm-gateway/tests/test_gateway.py) | 本地 |

## 验证记录

2026-11-20，阶段项目代码已完成协议、YAML 配置、能力路由、重试 / fallback、流式转发和 SQLite 用量的离线测试；随后实际启动服务，验证了 `/healthz`、`/readyz`、`POST /v1/chat/completions`、SSE Streaming 和 `/admin/usage`。当前配置只加载了主 Provider，备用 Provider 故障切换和 Docker 启动尚未真实验证。

个人学习状态为 `未开始`。阶段项目完成的标志是能解释每条路由和 Trace，并能独立改变 Provider 能力、优先级和错误条件后预测结果。

