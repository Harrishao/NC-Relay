import relay

PREFIX = "/st"


def should_respond(message):
    """仅响应以 /st 开头的消息"""
    if isinstance(message, str):
        return message.startswith(PREFIX)
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                text = seg.get("data", {}).get("text", "")
                if text.startswith(PREFIX):
                    return True
    return False


async def handle_message(websocket, data):
    """事件响应入口，过滤后分发"""
    if data.get("post_type") != "message":
        return

    message = data.get("message", "")
    if not should_respond(message):
        return

    msg_type = data.get("message_type")
    if msg_type == "private":
        user_id = data.get("user_id")
        if user_id and message:
            await relay.push_to_st(websocket, data)
            print(f"[responder] 转发 /st 消息到 ST, user_id={user_id}")
