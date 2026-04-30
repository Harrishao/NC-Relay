import json


async def _send_action(websocket, action, params, echo=None):
    payload = {"action": action, "params": params}
    if echo is not None:
        payload["echo"] = echo
    await websocket.send(json.dumps(payload, ensure_ascii=False))
    print(f"[echo] {json.dumps(payload, indent=2, ensure_ascii=False)}")


async def echo_private_msg(websocket, user_id, message):
    """回显私聊消息（仅在调试模式下调用）"""
    await _send_action(
        websocket,
        "send_private_msg",
        {"user_id": user_id, "message": message},
    )


async def echo_group_msg(websocket, group_id, message):
    """回显群聊消息（仅在调试模式下调用）"""
    await _send_action(
        websocket,
        "send_group_msg",
        {"group_id": group_id, "message": message},
    )
"""
随便写点注释，重新push一次
"""