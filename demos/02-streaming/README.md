# Streaming Demo

用一组可运行的小模块理解：模型增量输出怎样变成可重放、可取消、可恢复的 Agent 事件流。

配套笔记：[Streaming：让 Agent 执行过程可见、可停、可续](../../notes/01-llm-api/02-streaming.md)。

## 目标

- 观察真实模型的 `text.delta`、`model.finished` 和 `model.usage`。
- 区分 TTFT、生成耗时（GEN）和端到端耗时（E2E）。
- 理解 `bytes → SSE 帧 → RunEvent` 的边界。
- 实现 Run Store、Agent Loop、SSE Gateway、取消和 Checkpoint 的最小版本。

## 环境与依赖

要求 Python 3.11+、仓库根目录的 `.venv` 和一个 OpenAI Compatible 服务。

在仓库根目录安装本 Demo 的直接依赖：

```bash
uv pip install --python .venv/bin/python -r demos/02-streaming/requirements.txt
```

也可以恢复根目录的完整固定依赖：

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

根目录 `.env` 只保存本机配置，不提交到 Git：

```dotenv
AGENTOS_LLM_BASE_URL=https://example.invalid/v1
AGENTOS_LLM_API_KEY=
AGENTOS_LLM_MODEL=gpt-5.6-luna
```

脚本会读取已有环境变量，并回退读取仓库根目录 `.env`；不会把密钥打印到输出。若配置缺失，命令会明确报错。

## 示例入口

| 文件 | 作用 | 是否调用真实模型 |
| --- | --- | --- |
| [stream_chat.py](stream_chat.py) | 流式调用并输出指标 | 是 |
| [stream_model.py](stream_model.py) | 将供应商 chunk 归一化 | 入口是真实调用；测试可用替身 |
| [events.py](events.py) | RunEvent 与终态集合 | 否 |
| [sse_codec.py](sse_codec.py) | SSE 编码、心跳、拆包解析 | 否 |
| [run_store.py](run_store.py) | 内存事件 Store、序号和取消请求 | 否 |
| [agent_loop.py](agent_loop.py) | 与 HTTP 解耦的最小 Agent Loop | 可注入模型 |
| [gateway_fastapi.py](gateway_fastapi.py) | 创建、订阅、取消三个 HTTP 接口 | 是 |
| [sse_cli.py](sse_cli.py) | 从 stdin 消费 SSE 并渲染文本 | 否 |
| [checkpoint.py](checkpoint.py) | 检查点 JSON 保存和读取 | 否 |
| [streaming_retry.py](streaming_retry.py) | 业务事件产生前的有限重试 | 否 |
| [tests/test_streaming.py](tests/test_streaming.py) | 协议和状态边界测试 | 否 |

## 真实模型流式调用

```bash
# 默认问题，输出 JSON Lines。
.venv/bin/python demos/02-streaming/stream_chat.py

# 自定义问题和输出预算。
.venv/bin/python demos/02-streaming/stream_chat.py \
  --question "只用一句话解释 Streaming 是否会让推理更快。" \
  --max-output-tokens 128
```

输出示例（内容和数值会随模型变化）：

```json
{"type":"text.delta","data":{"delta":"Streaming "}}
{"type":"model.finished","data":{"finish_reason":"stop"}}
{"type":"model.usage","data":{"total_tokens":42}}
{"type":"metrics","data":{"ttft_ms":320.1,"generation_ms":850.4,"e2e_ms":1170.8}}
```

| 指标 | 含义 |
| --- | --- |
| TTFT | 请求开始到首个非空文本增量到达 |
| GEN | 首个文本增量到模型流结束 |
| E2E | 请求开始到流结束 |

首个 SDK chunk 可能只有 role 元数据，因此代码只用首个非空 `text.delta` 计算 TTFT。

## SSE CLI

CLI 不调用模型，只解析标准 SSE。先把事件写入文件，再消费：

```bash
cat > /tmp/events.sse <<'EOF'
id: 0
event: text.delta
data: {"run_id":"run_demo","seq":0,"type":"text.delta","data":{"delta":"你好"}}

id: 1
event: run.completed
data: {"run_id":"run_demo","seq":1,"type":"run.completed","data":{"status":"ok"}}

EOF

.venv/bin/python demos/02-streaming/sse_cli.py < /tmp/events.sse
```

客户端按 `run_id + seq` 去重；心跳是 SSE 注释，不会进入业务事件。

## FastAPI Gateway

启动本地 Gateway（需要真实模型配置）：

```bash
.venv/bin/python -m uvicorn gateway_fastapi:app \
  --app-dir demos/02-streaming \
  --host 127.0.0.1 \
  --port 8765
```

另开终端创建 Run：

```bash
RUN_ID=$(
  curl -sS -X POST http://127.0.0.1:8765/runs \
    -H 'content-type: application/json' \
    -d '{"question":"用一句话解释 Streaming。"}' \
  | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])'
)
echo "$RUN_ID"
```

订阅事件（直到收到唯一终态）：

```bash
curl -N "http://127.0.0.1:8765/runs/${RUN_ID}/events"
```

断线后可从指定序号继续。浏览器通常自动发送 `Last-Event-ID`，命令行也可用查询参数演示：

```bash
curl -N "http://127.0.0.1:8765/runs/${RUN_ID}/events?last_event_id=2"
```

请求协作式取消：

```bash
curl -sS -X POST "http://127.0.0.1:8765/runs/${RUN_ID}/cancel"
```

接口职责固定为：`POST /runs` 创建、`GET /runs/{run_id}/events` 订阅和重放、`POST /runs/{run_id}/cancel` 控制。断开 SSE 连接不会自动取消后台 Run。

## 本地验证

```bash
# 不调用模型，验证协议、终态、取消、重试和 Checkpoint。
.venv/bin/python -m unittest discover -s demos/02-streaming/tests -v

# 语法检查。
python3 -m compileall -q demos/02-streaming
```

2026-11-19 已验证：8 项离线测试通过；真实流式调用返回多个 `text.delta`、`model.finished`、`model.usage` 和三项指标；本地 FastAPI Gateway 实际完成 `POST /runs → GET /events`，收到 `run.completed`，并从 `last_event_id` 继续重放。这个结果只证明本地单进程链路可运行，不代表生产部署已验证。

## 核心要点速记（对应笔记 02）

对应笔记：[Streaming：让 Agent 执行过程可见、可停、可续](../../notes/01-llm-api/02-streaming.md)。

**Streaming 不是打字机效果，是 Agent Runtime 到交互层的事件通道。** 它的第一价值是可见性，不是更快。

1. **事件分三类。** 数据面（`text.delta`）、过程面（`tool.started` 等）、控制面（`run.completed` / `run.failed` / `run.cancelled`）。一个 Run 只有一个终态；`model.finished` 只表示模型流结束，不等于 `run.completed`。
2. **三层不要混。** `bytes → UTF-8 增量解码 → SSE 帧 → JSON → RunEvent`。一次读到的 chunk 不等于一个事件，可能是半个、一个或多个。
3. **三个接口分离。** `POST /runs` 创建、`GET /runs/{id}/events` 订阅、`POST /runs/{id}/cancel` 取消。断开订阅不等于取消任务。
4. **`run_id + seq` 是事件的稳定位置。** 用于排序、去重和重放；心跳是注释行，不占 `seq`。断线续传恢复的是事件，不是模型 Token。通知可以丢，事实事件不能丢。
5. **TTFT 记首个非空 `text.delta`。** TTFT（Time To First Token，首个内容到达客户端的时间）不能取第一个 chunk，它可能只有 role 元数据。GEN 是首个 delta 到流结束，E2E 是用户操作到最终完成。
6. **取消用状态机。** `running → cancelling → cancelled`（也可能进入 `completed` 或 `failed`）。协作式取消比强制中断安全，不要用 `except Exception` 吞掉 `asyncio.CancelledError`。工具超时只表示“没收到结果”，不表示“动作没发生”，要建模 `unknown` 状态。
7. **恢复分三种。** Transport Resume（重放事件，不调模型）、Model Retry（业务事件产生前才能重试）、Task Resume（崩溃后从 Checkpoint 继续）。已有业务事件后，不要重新生成再拼接。
8. **职责边界。** Loop 不懂 HTTP，Client 不懂模型 SDK，Gateway 不决定任务是否完成。
9. **对接 AG-UI 时不改内部事件。** 在网关出口加翻译层：`RunEvent → AG-UI 翻译层 → SSE → 前端`。笔记里的 AG-UI 事件名凭记忆写成，实现前要对照官方文档。

### 两篇笔记共通的三条主线

- 模型输出不可信，先校验再使用。
- 失败要分类，重试必须有界。
- 边界（权限、终态、取消、契约）由工程师定义。

### 需要留意的两点

1. **两套重试各有长短。** 笔记 01 的 [retry.py](../01-first-model-call/retry.py) 按错误类型筛选并带抖动，但没有总时间限制；本 Demo 的 [streaming_retry.py](streaming_retry.py) 有总时间预算，并在已有业务事件后停止，但对所有异常都重试，没有使用文件里的 `retryable_status`。
2. **恢复模块尚未接入运行路径。** [checkpoint.py](checkpoint.py) 和 `streaming_retry.py` 目前只被 `tests/test_streaming.py` 调用，没有接入 `agent_loop.py` 或 `gateway_fastapi.py`。笔记验收项“Checkpoint 可读取并继续下一步”因此还没有实现；SDK 的自动重试已关闭（`max_retries=0`），模型连接失败时现在不会重试。

## 教学边界

这是单进程教学实现：Store 在内存中、订阅用轮询、没有鉴权，也没有多进程共享和持久化事件。生产系统还需要数据库事件表、通知机制、权限控制、连接治理、幂等键、工具副作用状态和完整 Trace。

未覆盖的真实能力包括第二供应商切换、断网后的真实重连、真实工具取消和外部副作用恢复；对应代码只验证了本地协议边界。

