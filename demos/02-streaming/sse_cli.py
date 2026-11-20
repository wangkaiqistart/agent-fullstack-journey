"""从 stdin 消费 SSE；客户端只解析、去重和渲染，不调用模型。

用法示例（-N 让 curl 关闭输出缓冲，数据才能实时流过来）：
    curl -N http://localhost:8000/某个流式接口 | python sse_cli.py
"""

import sys

# TERMINAL_TYPES：终止事件类型集合（run.completed / run.failed / run.cancelled）
# 出现其中任何一个，说明这次运行已经彻底结束
from events import TERMINAL_TYPES
# SSEParser：解析器（parser），把收到的字节流还原成一个个 RunEvent 事件对象
from sse_codec import SSEParser


def main():
    parser = SSEParser()
    # seen（已见过的）：记录处理过的 (run_id, seq)，用来去重
    # run_id 表示“哪一次运行”，seq 表示“这次运行里的第几个事件”
    # 断线重连后服务端可能重放旧事件，靠它避免同一个事件被处理两次
    seen: set[tuple[str, int]] = set()

    # 用 sys.stdin.buffer（字节形式）而不是 sys.stdin（文本形式）：
    # 字节到文本的解码交给 SSEParser 自己做，这样一个中文被拆在两次读取之间也不会乱码
    for chunk in sys.stdin.buffer:
        # 调试：每次循环都打印读到的原始字节，输出到 stderr 避免和正常输出混在一起
        # print(f"[debug1] chunk={chunk!r}", file=sys.stderr)

        # feed_bytes（feed 意为“喂入”）：每喂一段字节，返回这一段里已经完整的事件
        # 结果可能是 0 个（只收到半个事件）、1 个，或多个（几个事件粘在一起）
        for event in parser.feed_bytes(chunk):
            # print(f"[debug2] chunk={chunk!r} event={event} /r/n", file=sys.stderr)
            key = (event.run_id, event.seq)
            if key in seen:
                # 已经处理过，跳过本次循环（continue 的作用）
                continue
            seen.add(key)

            if event.type == "text.delta":
                # text.delta：模型输出的一小段文字（delta 意为“增量”）
                # end=""：不换行，文字连续显示，看起来像打字机
                # flush=True：立即输出；不加的话 Python 会先存进缓冲区，就不是实时的了
                print(event.data.get("delta", ""), end="", flush=True)
            elif event.type in TERMINAL_TYPES:
                # 终止事件：先换行（\n），再打印事件类型和附带数据
                print(f"\n[{event.type}] {event.data}")
            # 其他类型（tool.started、model.usage 等）这里不处理，直接忽略

    # 输入结束后收尾：刷新 UTF-8 解码器；没有以空行结尾的半截事件会被丢弃
    parser.finish()


# 只有直接运行这个文件时才执行 main()；被别的文件 import 时不会自动运行
if __name__ == "__main__":
    main()
