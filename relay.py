import uuid
import json
import echo

# ST 扩展 WebSocket 连接
_st_ws = None

# relay_id → {napcat_ws, user_id} 映射
_pending = {}


def register_st(websocket):
    global _st_ws
    _st_ws = websocket
    print(f"[relay] ST 扩展已注册")


def unregister_st(websocket):
    global _st_ws
    if _st_ws is websocket:
        _st_ws = None
        print(f"[relay] ST 扩展已断开")


async def push_to_st(napcat_ws, data):
    """将 QQ 消息推送给 ST 扩展"""
    global _st_ws
    if _st_ws is None:
        print("[relay] 没有 ST 扩展连接，无法推送")
        return

    user_id = data.get("user_id")
    message = data.get("message", "")
    relay_id = str(uuid.uuid4())[:8]
    _pending[relay_id] = {"napcat_ws": napcat_ws, "user_id": user_id}

    payload = {
        "type": "qq_message",
        "relay_id": relay_id,
        "user_id": user_id,
        "message": message,
    }
    await _st_ws.send(json.dumps(payload, ensure_ascii=False))
    print(f"[relay] 推送 QQ 消息到 ST, relay_id={relay_id}")


async def handle_st_response(data):
    """处理 ST 扩展发回的 LLM 响应"""
    relay_id = data.get("relay_id")
    content = data.get("content")
    if relay_id and content:
        await send_to_qq(relay_id, content)


async def send_to_qq(relay_id, content):
    """LLM 响应回传 QQ"""
    info = _pending.pop(relay_id, None)
    if info is None:
        print(f"[relay] 未找到 relay_id={relay_id} 的待发送记录")
        return

    napcat_ws = info["napcat_ws"]
    user_id = info["user_id"]
    await echo.echo_private_msg(napcat_ws, user_id, content)
    print(f"[relay] LLM 回复已发送到 QQ, user_id={user_id}")
