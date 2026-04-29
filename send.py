import json


async def send_action(websocket, action, params, echo=None):
    """向 NapCat 发送 API 请求"""
    payload = {"action": action, "params": params}
    if echo is not None:
        payload["echo"] = echo
    await websocket.send(json.dumps(payload, ensure_ascii=False))
    print(f"[send.py] {json.dumps(payload, indent=2, ensure_ascii=False)}")


async def send_private_msg(websocket, user_id, message, echo=None):
    """发送私聊消息"""
    await send_action(
        websocket,
        "send_private_msg",
        {"user_id": user_id, "message": message},
        echo=echo,
    )


async def send_group_msg(websocket, group_id, message, echo=None):
    """发送群聊消息"""
    await send_action(
        websocket,
        "send_group_msg",
        {"group_id": group_id, "message": message},
        echo=echo,
    )
