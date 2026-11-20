# LLM Gateway Demo

用 FastAPI 建一个模型统一入口：上层只提交平台协议，Provider、模板、重试、Schema、流式和 Trace 都收敛在 Gateway 内部。

配套笔记：[LLM Gateway：把模型调用变成可治理的稳定边界](../../notes/01-llm-api/05-llm-gateway.md)。

## 目标

- 用 Pydantic 定义独立于供应商的请求和响应协议。
- 用 Provider Adapter 隔离 Base URL、模型名、密钥和 SDK 对象。
- 在 Gateway 集中管理 Prompt 模板、Structured Output、重试和备用模型。
- 记录模型、Prompt 版本、Token、耗时、尝试次数和状态。
- 保证流式输出首个增量后不切换模型重写。

## 环境

要求 Python 3.11+、`.venv` 和真实模型配置。依赖使用根目录固定版本：

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

主模型配置：

```dotenv
AGENTOS_LLM_BASE_URL=https://example.invalid/v1
AGENTOS_LLM_API_KEY=
AGENTOS_LLM_MODEL=gpt-5.6-luna
```

可选备用模型配置：

```dotenv
AGENTOS_ALT_LLM_BASE_URL=https://example.invalid/v1
AGENTOS_ALT_LLM_API_KEY=
AGENTOS_ALT_LLM_MODEL=backup-model
```

密钥只在 Gateway 内部读取，不出现在业务 Agent 请求协议中。SDK 自动重试已关闭，由 Gateway 统一控制。

## 示例入口

| 文件 | 作用 |
| --- | --- |
| [protocol.py](protocol.py) | Gateway 请求、响应、Usage、Trace 协议 |
| [prompt_store.py](prompt_store.py) | 受控 Prompt 名称、版本和变量 |
| [provider.py](provider.py) | OpenAI Compatible Provider Adapter |
| [gateway_core.py](gateway_core.py) | 协议转换、重试、fallback、Schema、Trace |
| [gateway_fastapi.py](gateway_fastapi.py) | `/chat`、`/stream`、`/trace` |
| [tests/test_gateway.py](tests/test_gateway.py) | 离线边界测试 |

## 启动 Gateway

```bash
.venv/bin/python -m uvicorn gateway_fastapi:app \
  --app-dir demos/05-llm-gateway \
  --host 127.0.0.1 \
  --port 8766
```

### 普通调用

```bash
curl -sS -X POST http://127.0.0.1:8766/chat \
  -H 'content-type: application/json' \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "用一句话解释 LLM Gateway。"}]
  }'
```

### 受控模板

```bash
curl -sS -X POST http://127.0.0.1:8766/chat \
  -H 'content-type: application/json' \
  -d '{
    "model": "default",
    "prompt_template": "kb-qa",
    "prompt_version": "2.1",
    "variables": {"language": "中文"},
    "messages": [{"role": "user", "content": "报销需要什么材料？"}]
  }'
```

### Structured Output

```bash
curl -sS -X POST http://127.0.0.1:8766/chat \
  -H 'content-type: application/json' \
  -d '{
    "model": "default",
    "schema_name": "agent_decision",
    "messages": [{"role": "user", "content": "请判断是否需要查询差旅报销制度。"}]
  }'
```

输出只有通过 Gateway 本地 Schema 校验的文本才会返回。

### 流式调用

```bash
curl -N -X POST http://127.0.0.1:8766/stream \
  -H 'content-type: application/json' \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "用三句话解释流式输出。"}]
  }'
```

Gateway 收到一个非空增量就转发一个 `content.delta`；首个增量之后不能切换备用模型重新拼接答案。

### Trace 查询

```bash
curl -sS http://127.0.0.1:8766/trace
curl -sS 'http://127.0.0.1:8766/trace?trace_id=trace_xxx'
```

教学版 Trace 包含 Provider、Prompt 版本、Token、耗时、尝试次数和状态；成本暂未接入具体价目表，返回 `null`。

## 离线验证

```bash
python3 -m compileall -q demos/05-llm-gateway
.venv/bin/python -m unittest discover -s demos/05-llm-gateway/tests -v
```

测试覆盖：未知模型、模板变量缺失、主模型有限重试后 fallback、Schema 失败不静默切换、流式增量边界和 Trace 记录。2026-11-20 已实际启动 Gateway，验证 `/chat`、`/stream` 和 `/trace`；Provider 故障切换仍只用替身验证，未向真实服务注入故障。

## 生产边界

这是单进程教学实现：Trace 在内存中、价格表为空、流式事件没有持久化序号和断线重放、鉴权和多租户隔离未实现。生产系统还需要持久化 Trace、成本配置、权限、限流、幂等键、连接治理和安全审计。

