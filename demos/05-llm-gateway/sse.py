"""教学版 SSE 编码；真实系统应补充事件序号和断线重放。"""

import json


def encode_event(event: dict) -> str:
    return "event: {0}\ndata: {1}\n\n".format(event["type"], json.dumps(event, ensure_ascii=False))
