"""SSE 编码与拆包解析；把字节流恢复为完整 RunEvent。"""

# codecs：提供“增量解码器”，能处理被拆成两半的中文字符
import codecs
import json
from collections.abc import Iterable

from events import RunEvent


# ---------- 编码：服务端把 RunEvent 变成字节，发给浏览器 ----------
def encode_sse(event: RunEvent) -> bytes:
    """编码一个业务事件；id 使用 Run 内 seq，心跳不走这里。"""
    # model_dump(mode="json")：把事件转成纯字典，时间等类型也转成可序列化的字符串
    payload = event.model_dump(mode="json")
    # 一个 SSE 事件由若干“字段: 值”的行组成
    lines = [
        f"id: {event.seq}",  # 事件编号；浏览器断线重连时会把最后收到的 id 带回来（Last-Event-ID）
        f"event: {event.type}",  # 事件名；浏览器端可以按名字分别监听
        # data：真正的内容。ensure_ascii=False 保留中文；separators 去掉多余空格，减小体积
        # JSON 会把内容里的换行转义成 \n 两个字符，所以 data 永远只占一行
        "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "",  # 末尾放一个空字符串，join 之后会多出一个换行
    ]
    # 各行用 \n 连接，再补一个 \n，结果以“空行”（\n\n）结尾；空行就是“这个事件结束了”的信号
    return ("\n".join(lines) + "\n").encode("utf-8")  # 网络传输的是字节，所以转成 UTF-8


def encode_heartbeat() -> bytes:
    """SSE 注释行只保活连接，不占用业务 seq。"""
    # 以冒号开头的行是 SSE 的“注释”，接收方会忽略它。
    # 作用是定期发点东西，防止中间的代理或网关以为连接空闲而把它断掉
    return b": heartbeat\n\n"


# ---------- 解码：客户端把收到的字节还原成 RunEvent ----------
class SSEParser:
    """支持任意字节拆分、多个事件粘连和 UTF-8 多字节字符。"""

    # 网络不保证“一次收到的数据 = 一个完整事件”：可能只收到半个事件，
    # 也可能一次收到好几个事件。所以解析器要自己攒数据，凑够一行再处理。
    def __init__(self):
        # 增量解码器：一个中文占 3 个字节，如果刚好被拆在两次接收之间，
        # 它会先记住前面的字节，等后面的字节到了再合成完整的字
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._buffer = ""  # 已解码、但还没凑成完整一行的文字
        # 下面三个是“当前正在拼装的事件”的临时状态
        self._event = "message"  # event 字段，SSE 规定缺省值是 message
        self._event_id = ""  # id 字段
        self._data: list[str] = []  # data 字段，可能有多行，所以用列表

    def feed_bytes(self, chunk: bytes) -> list[RunEvent]:
        """喂入一段收到的字节，返回这一段里已经完整的事件（可能是 0 个、1 个或多个）。"""
        # final=False：告诉解码器“后面还有数据”，末尾不完整的字符先留着
        self._buffer += self._decoder.decode(chunk, final=False)
        events: list[RunEvent] = []
        # 缓冲区里只要还有换行，就说明至少有一整行可以处理
        while "\n" in self._buffer:
            # 只切第一个换行：line 是这一行，剩下的放回缓冲区
            line, self._buffer = self._buffer.split("\n", 1)
            # rstrip("\r")：兼容 Windows 风格的 \r\n 换行
            events.extend(self._feed_line(line.rstrip("\r")))
        return events

    def finish(self) -> list[RunEvent]:
        """连接结束时刷新 UTF-8 解码器；不完整 SSE 帧直接丢弃。"""
        # final=True：不会再有数据了，把解码器里残留的字节吐出来
        self._buffer += self._decoder.decode(b"", final=True)
        if self._buffer:
            self._feed_line(self._buffer)
            self._buffer = ""
        # 没有空行收尾的事件永远不会被派发，所以这里固定返回空列表
        return []

    def _feed_line(self, line: str) -> list[RunEvent]:
        """处理一行：空行表示事件结束，其余行记录字段。"""
        if not line:  # 空行：一个事件结束，尝试组装
            return self._finish_event()
        if line.startswith(":"):  # 注释行（包括心跳），直接忽略
            return []
        # partition 按第一个冒号切成三份：字段名、冒号本身、值
        field, separator, value = line.partition(":")
        if not separator:  # 这一行没有冒号，格式不对，忽略
            return []
        # SSE 规定：冒号后面如果有一个空格，要去掉。所以 "data: abc" 的值是 "abc"
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "id":
            self._event_id = value
        elif field == "data":
            # 多行 data 会被依次放进列表，事件结束时用 \n 拼回去
            self._data.append(value)
        # retry 等 SSE 控制字段由客户端连接层处理，不进入业务事件。
        return []

    def _finish_event(self) -> list[RunEvent]:
        """遇到空行时调用：把攒好的 data 解析成 RunEvent。"""
        if not self._data:  # 没有 data（例如连续多个空行），没有事件可产出
            self._reset()
            return []
        try:
            # 多行 data 用 \n 拼接，再解析成字典
            raw = json.loads("\n".join(self._data))
            # 用 pydantic 校验：类型不在 EventType 里、多出未知字段等都会失败
            event = RunEvent.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            # 未知或损坏事件不能让客户端崩溃；重连时由服务端按 seq 重放。
            self._reset()
            return []
        self._reset()
        return [event]

    def _reset(self):
        """清空临时状态，准备拼装下一个事件。"""
        self._event, self._event_id, self._data = "message", "", []


def parse_chunks(chunks: Iterable[bytes]) -> list[RunEvent]:
    """便捷函数：一次性解析一组字节块，主要给测试用。"""
    parser = SSEParser()
    result: list[RunEvent] = []
    for chunk in chunks:
        result.extend(parser.feed_bytes(chunk))
    parser.finish()
    return result
