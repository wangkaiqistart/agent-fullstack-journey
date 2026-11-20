"""真实模型流式调用：输出内部事件，并打印 TTFT / GEN / E2E。"""

# argparse：Python 自带的“命令行参数解析”工具，用来读取 --question 之类的参数
import argparse
# json：用来把 Python 字典转成 JSON 字符串打印出来
import json

# StreamMetrics：自己写的“计时器”，记录首字耗时(TTFT)、生成耗时、总耗时
from metrics import StreamMetrics
# create_async_client：读取 .env 配置并创建异步客户端
# run_async：启动异步程序，并把常见错误转成友好提示
from settings_stream import create_async_client, run_async
# OpenAIChatStreamingAdapter：适配器，把 OpenAI 格式的流转换成项目内部统一的“事件”
from stream_model import OpenAIChatStreamingAdapter


# async def 表示这是“异步函数”：等网络数据时不会卡死，可以让出执行权
async def main():
    # ---------- 1. 解析命令行参数 ----------
    parser = argparse.ArgumentParser(description=__doc__)  # description 直接复用文件开头的说明
    # --question：要问模型的问题，不传就用默认问题
    parser.add_argument("--question", default="用三句话解释 Streaming 和普通一次性响应的区别。")
    # --max-output-tokens：限制模型最多输出多少 token（token 可理解为“词片段”，是模型计费和长度的单位）
    parser.add_argument("--max-output-tokens", type=int, default=512)
    args = parser.parse_args()  # 真正读取并解析命令行输入
    # 输出预算至少为 1，否则没有意义，直接报错
    if args.max_output_tokens < 1:
        raise ValueError("输出预算至少为 1")

    # ---------- 2. 准备客户端、计时器、适配器 ----------
    # client 是和模型服务通信的对象，model 是模型名称（都来自 .env 环境变量）
    client, model = create_async_client()
    # 创建计时器，并立刻记下“开始时间”
    metrics = StreamMetrics.start()
    # 适配器：负责发请求并把返回的数据块转换成内部事件
    adapter = OpenAIChatStreamingAdapter(client, model, max_output_tokens=args.max_output_tokens)

    # try/finally：不管中间成功还是出错，最后都一定会执行 finally 里的“关闭客户端”
    try:
        # ---------- 3. 流式读取模型输出 ----------
        # async for：每当模型吐出一小段内容，就拿到一个 event，处理完再等下一个
        # messages 格式是 [{"role": 角色, "content": 内容}]，这里 role="user" 表示用户提问
        async for event in adapter.stream([{"role": "user", "content": args.question}]):
            # text.delta：模型输出了一小段文字（delta 意思是“增量、新增的一小块”）
            if event.type == "text.delta":
                # 告诉计时器“收到文字了”；计时器只会记录第一次，用来算 TTFT
                metrics.observe_text()
            # model.finished：模型表示“我说完了”
            if event.type == "model.finished":
                # 记下结束时间
                metrics.finish()
            # 把事件打印成一行 JSON。ensure_ascii=False 让中文正常显示，不变成 \uXXXX
            # flush=True 表示立刻输出，不在缓冲区里等待，这样才能看到“边生成边显示”的效果
            print(json.dumps({"type": event.type, "data": event.data}, ensure_ascii=False), flush=True)

        # 兜底：如果流结束了却没收到 model.finished 事件，这里补记结束时间
        if metrics.finished_at is None:
            metrics.finish()
        # ---------- 4. 打印耗时统计 ----------
        # ttft_ms：首字耗时；generation_ms：从首字到结束的生成耗时；e2e_ms：从开始到结束的总耗时（ms=毫秒）
        print(json.dumps({"type": "metrics", "data": metrics.as_dict()}, ensure_ascii=False), flush=True)
    finally:
        # 关闭客户端，释放网络连接
        await client.close()


# 只有“直接运行这个文件”时才执行；被别的文件 import 时不会自动运行
if __name__ == "__main__":
    # 启动异步的 main，并统一处理 API 错误、参数错误
    run_async(main)
