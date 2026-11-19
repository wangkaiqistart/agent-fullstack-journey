"""本地只读教学工具：模型请求真实，订单数据为模拟数据。"""

import json

TOOL_NAME = "get_order_status"
TOOL_DESCRIPTION = "查询本地模拟订单状态，不连接真实订单系统。"
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"order_id": {"type": "string", "description": "订单编号"}},
    "required": ["order_id"],
    "additionalProperties": False,
}


def execute(name, arguments):
    # 模型只提出调用请求，程序校验后才执行。
    if name != TOOL_NAME:
        raise ValueError("工具未注册")
    try:
        args = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("工具参数必须是 JSON 字符串") from None
    if not isinstance(args, dict) or set(args) != {"order_id"}:
        raise ValueError("工具参数必须只包含 order_id")
    order_id = args["order_id"]
    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("order_id 必须是非空字符串")

    return json.dumps({
        "order_id": order_id,
        "status": "in_transit" if order_id == "ORD-DEMO-001" else "not_found",
        "source": "local-demo",
    }, ensure_ascii=False)

