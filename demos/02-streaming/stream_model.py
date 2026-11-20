"""把 OpenAI Compatible Chat 流转换为供应商无关的 ModelStreamEvent。"""

# AsyncIterator：类型标注，表示“可以用 async for 一个个取值的对象”
from collections.abc import AsyncIterator
# dataclass：装饰器，自动帮类生成 __init__ 等方法，适合只存数据的类
from dataclasses import dataclass
# Any：任意类型；Protocol：用来定义“接口”（只规定要有什么方法，不管具体是谁实现的）
from typing import Any, Protocol


# frozen=True 表示创建后不能再修改字段，事件一旦产生就不应该被改动
@dataclass(frozen=True)
class ModelStreamEvent:
    """项目内部统一的事件格式：不管底层是哪家模型，上层都只认这个。"""

    type: str  # 事件类型，例如 "text.delta"、"model.finished"、"model.usage"
    data: dict[str, Any]  # 事件携带的数据，例如 {"delta": "你好"}


class StreamingModel(Protocol):
    """“流式模型”的接口约定：只要有一个 stream 方法，就算符合。

    这样以后换成别家模型，只要也实现 stream，上层代码不用改。
    """

    # 参数是消息列表，返回的是可以 async for 的事件流；“...”表示这里只定义接口，不写实现
    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[ModelStreamEvent]: ...


# 函数里有 yield，说明它是“异步生成器”：每 yield 一次，就往外送出一个事件
async def normalize_chat_stream(stream) -> AsyncIterator[ModelStreamEvent]:
    """处理无 choices、空 delta、结束原因和 usage-only chunk。"""
    # chunk 是模型服务返回的一个“数据块”（流式返回会被切成很多个小块）
    async for chunk in stream:
        # choices 是模型给出的候选回答列表；有的块里它是空的（比如只带用量信息的最后一块）
        # 所以先判断：有就取第一个，没有就是 None，避免下标越界报错
        choice = chunk.choices[0] if chunk.choices else None

        # delta 是这一块里“新增的文字”；content 为空（None 或 ""）时说明这块没文字，直接跳过
        if choice and choice.delta.content:
            # 送出“文字增量”事件，上层收到后就可以立即显示
            yield ModelStreamEvent("text.delta", {"delta": choice.delta.content})

        # finish_reason 是“结束原因”，只有最后一块才有值
        # 常见值：stop（正常说完）、length（达到长度上限被截断）
        if choice and choice.finish_reason:
            yield ModelStreamEvent("model.finished", {"finish_reason": choice.finish_reason})

        # usage 是 token 用量统计（输入多少、输出多少），一般只在最后一块出现
        # 这个块往往没有 choices，所以上面两个 if 不会触发，只会走这里
        if chunk.usage:
            yield ModelStreamEvent(
                "model.usage",
                # model_dump 把 SDK 的对象转成普通字典；mode="json" 保证里面都是可转 JSON 的类型
                chunk.usage.model_dump(mode="json"),
            )


class OpenAIChatStreamingAdapter:
    """Adapter 只产出内部事件，不拼 SSE 字符串。"""

    # Adapter（适配器）：把 OpenAI 的接口“包一层”，对外变成统一的 StreamingModel 形式
    # SSE（Server-Sent Events）是服务器向浏览器持续推送数据的网络格式，
    # 这里刻意不处理它，让“调模型”和“怎么推给前端”两件事分开

    # 参数前面的 * 表示：它后面的参数必须写成 max_output_tokens=xxx 的形式，不能只写位置
    def __init__(self, client, model: str, *, max_output_tokens: int = 1024):
        self.client = client  # 和模型服务通信的客户端
        self.model = model  # 模型名称
        self.max_output_tokens = max_output_tokens  # 最多输出多少 token，防止回答过长

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[ModelStreamEvent]:
        # 向模型发起请求；await 表示等待网络返回（等待期间不阻塞其他任务）
        stream = await self.client.chat.completions.create(
            model=self.model,  # 用哪个模型
            messages=messages,  # 对话内容
            stream=True,  # 关键：开启流式，模型会一块一块返回，而不是一次返回全部
            max_completion_tokens=self.max_output_tokens,  # 输出长度上限
            # 默认流式不返回用量统计；加上这个，最后会多一个带 usage 的块
            stream_options={"include_usage": True},
        )
        # 把原始数据块交给上面的函数转换，转换出的每个事件原样往外送
        async for event in normalize_chat_stream(stream):
            yield event
