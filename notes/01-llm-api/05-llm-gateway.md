---
title: LLM Gateway：把模型调用变成可治理的稳定边界
date: 2026-11-20
tags: [ai-agent, llm-gateway, provider-adapter, observability]
note_type: 技术笔记
learning_status: 未开始
---

# LLM Gateway：把模型调用变成可治理的稳定边界

**LLM Gateway 的价值不是多转发一次 HTTP，而是把模型调用规则集中到一个可治理的边界中。**

配套代码：[demos/05-llm-gateway](../../demos/05-llm-gateway/README.md)。

## 阅读导航

| 主题 | 要回答的问题 |
| --- | --- |
| [1. 为什么需要 Gateway](#1-为什么需要-gateway) | 为什么 Agent 不应该各自直连模型？ |
| [2. 独立请求协议](#2-独立请求协议) | 怎样隔离供应商差异？ |
| [3. Provider Adapter](#3-provider-adapter) | Base URL、模型名和 SDK 对象放在哪里？ |
| [4. 请求转换](#4-请求转换) | Gateway 内部怎样调用真实模型？ |
| [5. Streaming](#5-streaming) | 为什么必须边接收边转发？ |
| [6. Prompt 模板](#6-prompt-模板) | 为什么模板需要集中管理和版本追踪？ |
| [7. 重试与 fallback](#7-重试与-fallback) | 怎样避免调用爆炸和错误拼接？ |
| [8. Token、Cost、Latency、Trace](#8-tokencostlatencytrace) | 每次调用应该记录什么？ |
| [9. FastAPI 入口](#9-fastapi-入口) | 怎样提供统一 `/chat`、`/stream`、`/trace`？ |
| [10. 验收](#10-验收) | 哪些不变量证明 Gateway 真的稳定？ |

## 1. 为什么需要 Gateway

没有 Gateway 时，每个 Agent 都可能自己保存密钥、拼接 Base URL、选择模型、管理重试和解析响应。模型更换或规则修改时，所有业务服务都要跟着改。

```text
Agent / RAG / Planning
          ↓ 统一请求
FastAPI LLM Gateway
  ├─ Pydantic 请求校验
  ├─ Prompt 模板渲染
  ├─ 模型白名单与能力校验
  ├─ Provider Adapter
  ├─ 重试与备用模型
  ├─ Structured Output 出口校验
  ├─ Streaming
  └─ Token / Cost / Latency / Trace
```

Gateway 的核心价值：

- 上层只依赖平台协议；
- 密钥和供应商细节集中管理；
- 失败、重试和备用策略统一；
- 模型、Prompt 版本、成本和延迟可观测；
- 普通调用和流式调用有一致边界。

## 2. 独立请求协议

如果上层直接提交供应商原始请求，Gateway 只是透明代理，供应商差异仍然泄漏到 Agent 中。

Gateway 应定义自己的 Pydantic 请求模型。上层只提交：

- 平台模型名；
- Prompt 模板名称和版本；
- 消息；
- 业务 Schema 名称；
- 输出预算。

上层不应该提交：

- 供应商真实 Base URL；
- API Key；
- SDK 专属对象；
- 供应商响应字段路径；
- 未经过平台允许的重试次数。

核心原则：**协议隔离——上层不感知供应商，Gateway 不暴露实现。**

项目的 [protocol.py](../../demos/05-llm-gateway/protocol.py) 定义 `ChatRequest`、`LLMResponse`、`Usage` 和 `TraceRecord`。

## 3. Provider Adapter

OpenAI Compatible 减少了适配成本，但以下内容仍然需要集中管理：

| 差异 | Gateway 的处理 |
| --- | --- |
| Base URL | Provider 配置，不出现在上层请求 |
| 模型名 | 平台名映射到供应商模型名 |
| API Key | 只在 Gateway 进程读取 |
| Structured Output 能力 | 按 Provider 能力选择 `json_schema` 或其他模式 |
| SDK 响应对象 | 留在 Adapter 内部 |

Provider Adapter 的出口应该是自己的普通对象：

```text
Pydantic Message → Provider Adapter → Chat Completions → str + Usage
```

SDK 的 `completion` 对象不能穿过 Adapter。Gateway 其他部分只消费 `text`、`Usage` 和统一错误，不与供应商响应类型耦合。

项目的 [provider.py](../../demos/05-llm-gateway/provider.py) 关闭 SDK 自动重试，并把普通调用和流式调用统一为 Provider 方法。

## 4. 请求转换

Gateway 的转换链路：

1. FastAPI 接收 JSON；
2. Pydantic 校验平台请求；
3. 渲染受控 Prompt 模板；
4. 把 `Message` 转成 Provider 字典；
5. Provider 调用真实模型；
6. 提取完整文本和 Usage；
7. 进行 Structured Output 出口校验；
8. 返回平台自己的 `LLMResponse`，并写入 Trace。

模板错误、未知模型和 Schema 错误使用稳定错误码，例如：

| 错误码 | 含义 |
| --- | --- |
| `unknown_model` | 平台模型名不在白名单 |
| `unknown_prompt_template` | 模板或版本不存在 |
| `missing_prompt_variable` | 必填模板变量缺失 |
| `schema_validation_failed` | 返回文本未通过业务 Schema |
| `provider_unavailable` | 重试和 fallback 后仍不可用 |

## 5. Streaming

真正的流式代理应该收到一个增量块，就立即向下游发送一个增量块：

```text
Provider SSE chunk 1 → Gateway content.delta 1 → Agent
Provider SSE chunk 2 → Gateway content.delta 2 → Agent
Provider SSE chunk 3 → Gateway content.delta 3 → Agent
```

不能把完整响应收完后再一次性返回，否则只是“普通调用外面套了一个 StreamingResponse”。

流式调用还有一个关键不变量：**首个增量输出后，不能切换模型重新生成并拼接。**

原因是客户端已经看到了部分答案，切换模型会造成重复、顺序错乱或语义断裂。首个增量之前可以按策略有限重试；首个增量之后只能发送失败事件或结束状态。

项目的 [gateway_core.py](../../demos/05-llm-gateway/gateway_core.py) 和 [gateway_fastapi.py](../../demos/05-llm-gateway/gateway_fastapi.py) 展示了最小边界。

## 6. Prompt 模板

如果每个 Agent 都传入完整 System Prompt，同一份规则会散落在多个服务中。模板修改后，很难知道哪些调用已经升级，也无法从日志判断一次调用使用了哪个版本。

Gateway 应按“名称 + 版本”管理受控模板：

```text
kb-qa · v2.1
       ↓ Gateway 渲染
完整 System Prompt
       ↓ Trace 记录名称和版本
```

模板集中管理不等于自动消除 Prompt 注入。变量仍可能来自不可信输入，必须继续处理：

- 哪些变量允许进入 System Prompt；
- 变量长度和内容边界；
- 固定规则和外部数据分区；
- 缺失变量的失败方式。

## 7. 重试与 fallback

如果 SDK、Gateway 和 Agent Loop 都自动重试，一次任务可能产生远超预期的调用：

```text
SDK × 3 × Gateway × 2 × Agent Loop × 2 = 12 次调用
```

因此：

- 关闭 SDK 隐式重试；
- 由 Gateway 明确尝试次数和总预算；
- 只对明确的暂时性错误重试；
- 主模型连续失败后才考虑备用模型；
- 记录每次尝试和最终 Provider。

本 Demo 的同步调用示例是：主 Provider 最多调用两次，仍失败再使用备 Provider。真实系统还应加入指数退避、jitter、429 / 5xx 白名单和总时间预算。

Structured Output 校验失败不应静默切换模型重写，因为这可能掩盖协议问题；应返回稳定的 `schema_validation_failed`，由上层决定是否进入有限纠错流程。

## 8. Token、Cost、Latency、Trace

模型调用不只关心成功或失败，还要记录资源和过程：

| 指标 | 含义 | 影响 |
| --- | --- | --- |
| Token | 输入 + 输出数量 | 成本、上下文窗口、输出长度 |
| Cost | 模型价格 × Token | 预算和成本归因 |
| Latency | 请求发出到响应完成 | 用户体验和 SLA |
| Trace | 一次调用的关联标识 | 定位重试、fallback 和错误 |

每次调用至少记录：

- 模型和 Provider；
- Prompt 名称和版本；
- 输入、输出、总 Token；
- Cost；
- Latency；
- 尝试次数；
- 成功或失败状态；
- 稳定错误码。

成本必须基于当前价目表计算，不能把 Token 数量直接当作金额。教学 Demo 中 `cost` 暂为空，避免编造价格。

## 9. FastAPI 入口

推荐的统一入口：

| 接口 | 作用 |
| --- | --- |
| `POST /chat` | 普通完整响应 |
| `POST /stream` | 增量事件流 |
| `GET /trace` | 查询最近调用 Trace |

调用方只需要平台协议：

```json
{
  "model": "default",
  "messages": [{"role": "user", "content": "解释 Gateway"}],
  "max_output_tokens": 512
}
```

业务 Agent 中不应出现供应商 API Key 和 Base URL。

## 10. 验收

至少验证以下场景：

1. 正常文本请求返回 `LLMResponse`；
2. 未知模型返回 `unknown_model`；
3. 模板版本不存在返回 `unknown_prompt_template`；
4. 模板变量缺失返回 `missing_prompt_variable`；
5. 合法 JSON 但不符合业务 Schema 返回 `schema_validation_failed`；
6. 主模型暂时失败时有限重试，再 fallback 到备用模型；
7. 流式请求逐块产生 `content.delta`；
8. 流开始后失败不能静默换模型重写；
9. 成功和失败调用都能查询 Trace；
10. 业务 Agent 不保存供应商密钥和地址。

三个必须保持的不变量：

| 不变量 | 含义 |
| --- | --- |
| Schema 不通过不能进入 Loop | 非法输出不能触发工具副作用 |
| 首块之后不能切换模型重写 | 防止重复或拼接错误 |
| 上层只依赖统一协议 | 主模型和备用模型可以替换而不改业务代码 |

## 示例索引

| 能力 | 代码 | 方式 |
| --- | --- | --- |
| 请求 / 响应协议 | [protocol.py](../../demos/05-llm-gateway/protocol.py) | 本地 |
| Prompt 模板 | [prompt_store.py](../../demos/05-llm-gateway/prompt_store.py) | 本地 |
| Provider Adapter | [provider.py](../../demos/05-llm-gateway/provider.py) | 真实入口 |
| Gateway 核心 | [gateway_core.py](../../demos/05-llm-gateway/gateway_core.py) | 本地 + 真实入口 |
| FastAPI 接口 | [gateway_fastapi.py](../../demos/05-llm-gateway/gateway_fastapi.py) | FastAPI |
| 离线边界测试 | [tests/test_gateway.py](../../demos/05-llm-gateway/tests/test_gateway.py) | 本地 |

## 验证记录

2026-11-20，已完成 Gateway 协议、模板变量、有限重试 / fallback、Schema 失败、流式增量和 Trace 的离线测试。随后启动 FastAPI 实际验证了 `/chat` 返回统一 `LLMResponse`、`/stream` 逐块输出 `content.delta`、`/trace` 可查询成功调用。备用模型故障切换仍只用替身验证，未向真实服务注入故障。

个人学习状态为 `未开始`。下一步应修改主模型失败场景、配置备用模型、断开流式连接，并解释每一条 Trace 和每一个错误码的来源。

