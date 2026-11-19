# 模型 API 与 Agent 工程示例

目标：从真实模型调用出发，理解参数、上下文、输出契约、失败恢复与模型适配，最后生成可校验的修改计划。

配套文档：[从模型 API 到可控的 Agent Harness](../../notes/01-llm-api/01-从模型API到可控的Agent-Harness.md)。

## 示例入口

| 顺序 | 示例 | 重点 |
| --- | --- | --- |
| 1 | [chat_completions.py](chat_completions.py) | 真实：`messages` → `choices[0].message`，检查 `finish_reason` |
| 2 | [responses.py](responses.py) | 真实：`input` → `output`，检查 `status`，读取 `output_text` |
| 3 | [chat_completions_tools.py](chat_completions_tools.py) | 真实：`tool_calls` → `role=tool`，用 `tool_call_id` 对应 |
| 4 | [responses_tools.py](responses_tools.py) | 真实：`function_call` → `function_call_output`，用 `call_id` 对应 |
| 5 | [chat_completions_image.py](chat_completions_image.py) | 真实：同一条消息包含 `text` 与 `image_url` |
| 6 | [responses_image.py](responses_image.py) | 真实：同一条输入包含 `input_text` 与 `input_image` |
| 7 | [context_budget.py](context_budget.py) | 真实：按字符裁剪历史；支持本地 `--dry-run` |
| 8 | [awkward_knobs.py](awkward_knobs.py) | 真实：单独调整 temperature 或 top_p |
| 9 | [output_limit.py](output_limit.py) | 真实：输出预算、截断与用量异常检查 |
| 10 | [schema.py](schema.py)、[validate_plan.py](validate_plan.py) | 本地：严格字段与跨字段校验 |
| 11 | [business_guard.py](business_guard.py) | 本地：工作区路径与白名单校验 |
| 12 | [structured_output.py](structured_output.py) | 真实：JSON Schema 生成 + 本地校验 |
| 13 | [retry.py](retry.py)、[retry_demo.py](retry_demo.py) | 前者真实调用；后者离线故障模拟 |
| 14 | [model_adapter.py](model_adapter.py)、[adapter_demo.py](adapter_demo.py) | 前者定义统一接口；后者调用两种真实 API |
| 15 | [mini_agent.py](mini_agent.py) | 真实：计划生成、有限字段修复、路径校验与 Trace |

**表中标为“真实”的入口默认调用模型服务。** 订单工具在本地执行，只返回模拟数据。配置在 [settings.py](settings.py)，工具在 [order_tool.py](order_tool.py)。上下文实验支持 `--dry-run`，仅查看本地裁剪。

## 运行

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/)；SDK 固定为 `openai==3.51.0`。

在仓库根目录安装依赖到本地虚拟环境：

```bash
uv venv --allow-existing .venv
uv pip install --python .venv/bin/python -r demos/01-first-model-call/requirements.txt
```

上面安装 Demo 的直接依赖；恢复当前项目环境的全部固定版本，使用根目录的 [requirements.txt](../../requirements.txt)：`uv pip install --python .venv/bin/python -r requirements.txt`。

在仓库根目录的 `.env` 中填写配置；没有文件时可复制仓库根目录的 `.env.example`。三个变量分别是 API 地址、密钥和模型：

```dotenv
AGENTOS_LLM_BASE_URL=https://g7e6ai.com/v1
AGENTOS_LLM_API_KEY=
AGENTOS_LLM_MODEL=gpt-5.6-luna
```

每个脚本单独运行：

```bash
.venv/bin/python demos/01-first-model-call/chat_completions.py
.venv/bin/python demos/01-first-model-call/responses.py
.venv/bin/python demos/01-first-model-call/chat_completions_tools.py
.venv/bin/python demos/01-first-model-call/responses_tools.py
```

代码自动加载配置，优先级为：已有环境变量 > Demo 目录的 `.env` > 仓库根目录的 `.env`。路径按脚本定位，不受运行目录影响。IDE 选择仓库的 `.venv/bin/python` 即可直接运行；`.env` 和 `.venv/` 均已被 Git 忽略。

## 上下文预算：先裁剪，再调用

目标：理解“历史消息不必全部发送”，以及裁剪可能丢失事实。

使用现有依赖和 `.env`，无需安装新库。在仓库根目录运行：

```bash
# 先看裁剪结果：不读取配置，也不调用模型。
.venv/bin/python demos/01-first-model-call/context_budget.py --dry-run

# 默认预算 100 字符，调用真实模型。
.venv/bin/python demos/01-first-model-call/context_budget.py

# 缩到 40 字符：实验编号被裁掉，观察模型是否承认不知道。
.venv/bin/python demos/01-first-model-call/context_budget.py --max-history-chars 40
```

固定历史有 6 条，包含早期练习、实验编号 `LAB-001` 和当前学习主题。最后问：“我正在学习什么？实验编号是什么？”

| 历史预算 | 本地裁剪结果 | 预期回答 |
| --- | --- | --- |
| 100 字符 | 保留最近 4 条、71 字符 | 上下文预算；`LAB-001` |
| 40 字符 | 保留最近 2 条、36 字符 | 上下文预算；实验编号不知道 |
| 0 字符 | 不保留历史 | 两项信息都不知道 |

脚本打印实际发送的消息、结束原因，以及服务端提供的 Token 用量。固定历史均为教学数据。

**记住：字符预算 ≠ Token 预算。** `build_messages()` 的函数默认参数为 `12_000`；命令行默认用 `100`，便于观察裁剪。只限制历史正文，`system`、当前任务和消息封装不计入其中；`max_completion_tokens=1024` 只限制输出，尚未实现总容量检查与输出空间预留。

这是按单条消息裁剪的教学版，可能保留孤立的 assistant 消息。生产实现应按完整对话轮次裁剪，保证工具请求与结果配对，并按目标模型的 tokenizer 计算预算。

2026-11-17，项目 Python 3.13.9 / OpenAI SDK 3.51.0，加载本地 `.env`，使用 `gpt-5.6-luna` 执行上面的两组真实请求：

| 历史预算 | 结束原因 | 实际回答 | 服务端报告的输入 / 输出 Token |
| --- | --- | --- | --- |
| 100 字符 | `stop` | 正确回答上下文预算、`LAB-001` | 4488 / 18 |
| 40 字符 | `stop` | 正确回答上下文预算；编号“不知道” | 4458 / 17 |

用量为网关返回的 `usage`，不是本地字符换算结果；未核实网关内部计数或附加上下文。0 字符仅验证本地裁剪，未调用模型。另已检查零预算、恰好预算、空历史、最新消息超限、负预算拒绝、历史顺序及原数据不变。

## 多模态：文字 + 图片

默认发送仓库自制的 [教学图片](assets/multimodal-example.png)，无需另找图片，无新增依赖。在仓库根目录运行：

```bash
.venv/bin/python demos/01-first-model-call/chat_completions_image.py
.venv/bin/python demos/01-first-model-call/responses_image.py
```

固定问题：数出彩色形状，识别颜色、形状与底部编号。预期识别出 **3 个形状：红色圆形、蓝色正方形、绿色三角形；编号 `DEMO-042`**。实际回答措辞不固定，应核对内容。

传自己的本地图片，路径按当前运行目录解释；带空格时加引号：

```bash
.venv/bin/python demos/01-first-model-call/chat_completions_image.py "/绝对路径/架构图.png" --question "用三句话解释这张架构图。"
.venv/bin/python demos/01-first-model-call/responses_image.py "/绝对路径/架构图.png" --question "用三句话解释这张架构图。"
```

也可以把路径替换为模型服务可访问的 HTTPS 图片地址。两种输入方式的区别：

- 本地图片：读取二进制 → Base64 编码 → `data:image/png;base64,...`，随请求发送；远程服务无法直接读取本机路径。
- HTTPS 图片：只发送 URL，由远程服务获取图片；`localhost` 地址通常不可达。

编码过程见 [image_input.py](image_input.py)。仅接受 PNG/JPEG/WebP；SVG、PDF 需先转换。示例是图片输入、文本输出，不生成图片。

| 内容块 | Chat Completions | Responses |
| --- | --- | --- |
| 文字 | `{"type": "text", "text": "问题"}` | `{"type": "input_text", "text": "问题"}` |
| 图片 | `{"type": "image_url", "image_url": {"url": "图片地址", "detail": "auto"}}` | `{"type": "input_image", "image_url": "图片地址", "detail": "auto"}` |

两种 API 的 `content` 都改为列表。增加图片时追加图片块即可；图片格式、尺寸和数量限制以所用模型与网关为准。

## Agent 工程示例

均在仓库根目录运行，使用已有 `.venv` 与 `.env`。新增的直接依赖 Pydantic 已存在于环境快照，版本不变。

```bash
# 固定同一问题和预算，默认重复请求两次；每次只调整一个采样参数。
.venv/bin/python demos/01-first-model-call/awkward_knobs.py --temperature 0.2
.venv/bin/python demos/01-first-model-call/awkward_knobs.py --top-p 0.9

# 请求 32 Token 输出，检查截断或网关未执行预算的情况。
.venv/bin/python demos/01-first-model-call/output_limit.py --max-tokens 32

# 本地 Schema / 业务校验，不发送请求。
.venv/bin/python demos/01-first-model-call/schema.py
.venv/bin/python demos/01-first-model-call/validate_plan.py
.venv/bin/python demos/01-first-model-call/business_guard.py

# 真实模型生成计划，再做字段与路径校验。
.venv/bin/python demos/01-first-model-call/structured_output.py

# 真实请求：只对暂时性错误有限重试。
.venv/bin/python demos/01-first-model-call/retry.py
# 离线模拟：两次超时后成功，只打印等待时间。
.venv/bin/python demos/01-first-model-call/retry_demo.py

# 两种真实 Adapter 复用同一个业务函数，发起两次请求。
.venv/bin/python demos/01-first-model-call/adapter_demo.py
# 最小规划 Agent，分别选择两种 API。
.venv/bin/python demos/01-first-model-call/mini_agent.py
.venv/bin/python demos/01-first-model-call/mini_agent.py --api responses
```

固定代码样本为 [assets/workspace/src/example.py](assets/workspace/src/example.py)，问题是让 `size(None)` 返回 `0`，其他输入仍使用 `len(x)`。预期输出 `action=edit`、`file_path=src/example.py`、`risk=low` 的计划；原因文本可以不同。只读样本并展示计划，不会修改文件。

| 防线 | 实现与停止条件 |
| --- | --- |
| 输出结构 | 请求配置 `json_schema`，本地用 `PatchPlan` 再校验；模型拒答或截断立即停止 |
| 字段关系 | `edit` 必须有路径，`finish` 的路径必须为 `null`；禁止多余字段和空白原因 |
| 路径范围 | 只允许工作区 `src/` 下的 `.py`，拒绝绝对路径、`..`、Windows 路径和通过符号链接越界 |
| 请求重试 | 最多尝试 3 次；等待 `0.5–0.7s`、`1.0–1.2s`；认证和参数错误不重试 |
| 字段修复 | MiniAgent 最多 2 轮（首次 + 一次修复）；路径越界直接停止，不交给模型放行 |
| 总请求次数 | MiniAgent 最多 6 次；每次请求超时 60 秒，尚未实现整段流程的总截止时间 |
| Trace | 输出链路 ID、模型、耗时、结束原因、字段差异和重试次数；不写入日志文件 |

路径检查用于计划预览；真实写入仍需权限、授权及执行时校验，不能把它当作文件系统沙箱。

默认两种 Adapter 使用同一模型服务，验证的是 API 适配，不能据此声称跨供应商切换通过。需要另一家服务时，在本地 `.env` 填写：

```dotenv
AGENTOS_ALT_LLM_BASE_URL=
AGENTOS_ALT_LLM_API_KEY=
AGENTOS_ALT_LLM_MODEL=
```

对 `adapter_demo.py` 传入 `--alternate`，第二次调用使用另一家 Responses 服务；对 `mini_agent.py` 传入 `--alternate --api chat` 或 `--alternate --api responses`，可选择另一家的 API。缺少备用配置会明确报错，不自动回退到主服务。

## 记住这些差异

| 观察点 | Chat Completions | Responses |
| --- | --- | --- |
| 行为要求 | `messages` 中的 `system` 消息 | `instructions` |
| 用户输入 | `messages` | `input` |
| 文本 | `choices[0].message.content` | `output_text` 汇总文本，`output` 保留完整结构 |
| 工具定义 | 嵌套在 `function` 中 | 名称、描述、参数平铺 |
| 工具请求 | `message.tool_calls` | `output` 中的 `function_call` |
| 回传关联 | `tool_call_id = call.id` | `call_id = call.call_id` |
| 输出上限 | `max_completion_tokens` | `max_output_tokens` |
| 完成判断 | 文本检查 `stop`；工具请求检查 `tool_calls` | 检查 `completed`，再看输出项类型 |

Chat 常见结束原因：`stop` 正常结束、`length` 达到上限、`tool_calls` 请求工具、`content_filter` 内容被过滤。Responses 若为 `incomplete`，检查 `incomplete_details.reason`。

**响应完成不等于任务完成。** 模型请求工具后，仍需程序校验参数、执行工具、回传结果，再让模型回答。

## 输入与验证结果

2026-11-16，Python 3.11.15 / OpenAI SDK 3.51.0，使用上述地址及模型，真实调用共 6 次：

| 示例与固定输入 | 预期 | 实际 |
| --- | --- | --- |
| Chat：`def size(x): return len(x)` 有什么风险？ | `stop` 与非空文本 | 通过，回答提到不支持 `len()` 时的 `TypeError` |
| Responses：同一问题 | `completed` 与文本 | 通过，输出包含 `reasoning`、`message` |
| Chat 工具：查 `ORD-DEMO-001` | 工具请求 → 执行 → 最终回答 | 通过，`tool_calls → stop`，最终说明“运输中、本地模拟数据” |
| Responses 工具：同一订单 | 工具请求 → 结果回传 → 最终回答 | 通过，两轮 `completed`，最终说明“运输中、本地模拟数据” |

本地检查：Python 语法、缺失配置、正常与未知订单、非法工具名、非法 JSON、参数类型与额外字段。另用本地构造响应检查截断、拒答、空内容和失败状态，确认异常响应不会执行工具；这些异常分支未向真实接口注入故障。真实调用结果随模型与网关变化，不代表学习者已掌握。

同日新增自动加载 `.env`：配置优先级与根目录回退检查通过；从其他工作目录使用项目 `.venv/bin/python` 运行，已读到本地当前配置 `gpt-5.5`，Chat 真实请求返回 HTTP 404，原因尚未确认。此结果与上表使用 `gpt-5.6-luna` 的验证分别记录。

同日新增图片实验：使用项目 Python 3.13.9、SDK 3.51.0，从 `/tmp` 运行上面的两个图片脚本，自动加载本地 `.env`（`gpt-5.6-luna`，地址同上），共 2 次真实请求。Chat 返回 `stop`，Responses 返回 `completed`；两者均正确识别三个形状、颜色与编号 `DEMO-042`。HTTPS 图片输入未执行真实验证。

图片示例的本地检查：Base64 编码与原文件一致、HTTPS 地址与自定义问题传递、空文件/缺失文件/不支持格式拒绝，以及通过 SDK 的 MockTransport 核对两种请求 JSON 和文本读取。默认脚本运行时使用真实接口。

## 限制与动手改

- 只演示同步调用和一轮工具执行；每个工具示例发起两次模型请求。超时为 60 秒，SDK 自动重试关闭。
- Responses 使用 `store=False`，第二轮手动携带历史输出；未依赖 `previous_response_id`。
- 不同网关支持范围不同；异常只输出类型与 HTTP 状态，不输出请求及错误正文。
- 把订单改成 `ORD-DEMO-999`：预期工具返回 `not_found`，观察模型是否如实回答。
- 把输出上限改成 `5`：观察是否出现 `length` / `incomplete`；不同模型不保证相同结果。
- 把 `tool_choice` 改为 `"auto"`：观察模型是否选择调用；此时“未收到工具请求”也是可能结果。
- 给图片示例更换一张图片和问题，核对回答是否来自图片，而不是仅根据问题猜测。

## 本次新增示例验证（2026-11-17）

环境：项目 Python 3.13.9、OpenAI SDK 3.51.0、Pydantic 2.14.3，使用本地 `.env` 中的服务与 `gpt-5.6-luna`。

| 示例 | 实际结果 |
| --- | --- |
| `awkward_knobs.py --temperature 0.2` | 两次真实回答“清单簿”“清单集”；低温不保证相同文本 |
| `awkward_knobs.py --top-p 0.9` | 两次真实回答“拾光清单”“清单簿” |
| `structured_output.py` | 真实返回 `edit`、`src/example.py`、`low`，字段与路径校验通过 |
| `retry.py` | 真实回答重试上限的作用，首次成功；没有人为触发真实服务故障 |
| `adapter_demo.py` | 首次 Chat 成功、Responses 超时；重跑两种真实 API 均成功 |
| `mini_agent.py` 两种 API | 均在第一轮生成合法 `edit` 计划，未发生字段修复和请求重试；没有修改样本 |
| `output_limit.py` | 当前网关未按预期执行输出上限，见下方说明；未验证到真实 `length` |

输出预算异常：请求 `max_completion_tokens=32`，服务端返回 `stop`、输出用量 `2359`；再用 `max_tokens=32` 对照，返回 `stop`、输出用量 `2284`。两种字段均未表现为 32 Token 上限，原因未核实。脚本已加入用量超额检查；第二次对照实际触发拒绝分支，退出码为 1，不采用完整答案。不能把“服务接受字段”当作预算生效，也不能仅凭字段被接受就声称采样参数已生效。

离线验证：

```bash
.venv/bin/python -m unittest discover -s demos/01-first-model-call/tests -v
```

9 项测试通过，覆盖严格字段、跨字段规则、路径穿越与符号链接、历史裁剪、重试耗尽及永久错误、Adapter 格式映射和未完成输出拒绝、Agent 有限修复与路径拒绝、主备配置隔离。测试替身只存在于离线测试；这些分支未全部向真实服务注入故障。

尚未实测：第二供应商切换、真实拒答、服务端限流 / 过载 / 截断、真实 Schema 修复流程。这里的“通过”表示示例行为已验证，不代表学习者已掌握。
