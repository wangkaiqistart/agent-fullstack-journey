# 阶段一：LLM 统一模型调用服务

这是第一阶段整合项目：把模型协议、Prompt、Provider、路由、重试、Streaming、Structured Output 和用量记录收敛成一个可部署的 OpenAI Compatible 服务。

前置拆解示例：[demos/05-llm-gateway](../../demos/05-llm-gateway/README.md)。本项目负责把这些语义组装成服务边界。

## 范围

- `POST /v1/chat/completions`：兼容 OpenAI Chat Completions 的普通和流式请求。
- `GET /healthz`、`GET /readyz`：存活和配置就绪检查。
- `GET /admin/providers`：查看 Provider 能力和健康状态，不返回密钥。
- YAML 管理 Provider、逻辑模型别名、优先级、能力和重试参数。
- SQLite 保存 Trace、Token、Latency、重试、fallback 和错误码。
- 主模型在首个内容块前失败时有限 fallback；流开始后不换模型拼接。

## 运行

安装阶段项目直接依赖：

```bash
uv pip install --python .venv/bin/python -r projects/01-llm-gateway/requirements.txt
```

复制配置并填写真实凭据：

```bash
cp projects/01-llm-gateway/gateway.example.yaml /tmp/gateway.yaml
export AGENTOS_LLM_BASE_URL=https://example.invalid/v1
export AGENTOS_LLM_API_KEY=
export AGENTOS_LLM_MODEL=gpt-5.6-luna
export GATEWAY_CONFIG=/tmp/gateway.yaml
```

启动：

```bash
.venv/bin/python -m uvicorn app.main:app \
  --app-dir projects/01-llm-gateway \
  --host 127.0.0.1 \
  --port 8770
```

默认网关鉴权关闭；设置 `GATEWAY_API_KEY` 后，请求必须带：

```bash
-H "authorization: Bearer $GATEWAY_API_KEY"
```

普通调用：

```bash
curl -sS http://127.0.0.1:8770/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"用一句话解释统一模型调用服务。"}]}'
```

流式调用：

```bash
curl -N http://127.0.0.1:8770/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"default","stream":true,"messages":[{"role":"user","content":"用三句话解释 Streaming。"}]}'
```

## 配置和模块

| 文件 | 责任 |
| --- | --- |
| [gateway.example.yaml](gateway.example.yaml) | Provider、模型别名、能力和重试配置 |
| [app/schemas.py](app/schemas.py) | 外部兼容协议与内部请求模型 |
| [app/config.py](app/config.py) | YAML + 环境变量加载 |
| [app/providers.py](app/providers.py) | OpenAI Compatible Adapter |
| [app/router.py](app/router.py) | 能力匹配、优先级和候选选择 |
| [app/gateway.py](app/gateway.py) | 普通调用、重试、fallback、流式边界 |
| [app/usage.py](app/usage.py) | SQLite Trace / Usage / Cost 记录 |
| [app/main.py](app/main.py) | FastAPI 路由、鉴权、限流、健康检查 |
| [tests/test_gateway.py](tests/test_gateway.py) | Fake Provider 驱动测试 |

## 测试

```bash
.venv/bin/python -m unittest discover -s projects/01-llm-gateway/tests -v
python3 -m compileall -q projects/01-llm-gateway
```

阶段项目验收重点：

- 上层只提交逻辑模型名，不提交供应商密钥和 Base URL；
- Provider 能力不满足时不进入错误调用；
- 普通调用失败可有限重试和 fallback；
- 首个流式 delta 后不切换模型重写；
- Structured Output 返回后仍做本地 Schema 校验；
- Trace 能回放 requested / resolved model、Provider、Token、耗时和错误码。

2026-11-20 已实际启动服务并验证 `/healthz`、`/readyz`、`POST /v1/chat/completions`、SSE Streaming 和 `/admin/usage`；当前配置只加载了主 Provider，备用 Provider 未配置。

## 当前边界

这是可运行的学习版：限流、熔断和 Trace 是单进程实现，SQLite 默认本地文件，未实现多副本共享状态、完整价格表、Docker 发布和生产级权限系统。后续接入 Agent Harness 时，Gateway 只负责模型执行与调用弹性；Run 状态、工具权限、业务终态和任务恢复仍由 Harness 负责。

