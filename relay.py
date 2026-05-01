import uuid
import json
import os
import configparser
import echo
import render

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_config = configparser.ConfigParser()
_config.read(os.path.join(BASE_DIR, "config.ini"))

RENDER_ENABLE = _config.getboolean("render", "enable", fallback=False)
RENDER_IMAGE_THRESHOLD = _config.getint("render", "image_threshold", fallback=500)
RENDER_INCLUDE_REASONING = _config.getboolean("render", "include_reasoning", fallback=True)
RENDER_IMAGE_WIDTH = _config.getint("render", "image_width", fallback=600)
RENDER_OUTPUT_DIR = os.path.join(BASE_DIR, "rendered")

_last_server_reasoning = None

_st_ws = None

# relay_id → {napcat_ws, user_id, group_id} 映射
_pending = {}

# 处理锁：一条消息处理完之前，阻止新的 /st
_processing_lock = False
_processing_relay_id = None


def is_locked():
    return _processing_lock


def acquire_lock(relay_id):
    global _processing_lock, _processing_relay_id
    if _processing_lock:
        return False
    _processing_lock = True
    _processing_relay_id = relay_id
    return True


def release_lock():
    global _processing_lock, _processing_relay_id
    _processing_lock = False
    _processing_relay_id = None


async def cancel_processing():
    global _processing_lock, _processing_relay_id
    relay_id = _processing_relay_id
    if relay_id:
        _pending.pop(relay_id, None)
        if _st_ws:
            await _st_ws.send(json.dumps({"type": "stop", "relay_id": relay_id}, ensure_ascii=False))
            print(f"[relay] 已发送停止指令到 ST, relay_id={relay_id}")
    release_lock()
    return relay_id


def register_st(websocket):
    global _st_ws
    _st_ws = websocket
    print(f"[relay] NC-Relay2ST 脚本已注册")


def unregister_st(websocket):
    global _st_ws
    if _st_ws is websocket:
        _st_ws = None
        release_lock()
        print(f"[relay] NC-Relay2ST 脚本已断开, 已释放处理锁")


def set_last_server_reasoning(reasoning):
    global _last_server_reasoning
    if reasoning:
        _last_server_reasoning = reasoning


async def push_to_st(napcat_ws, data):
    global _st_ws
    if _st_ws is None:
        print("[relay] 未连接到脚本，无法推送")
        return None

    user_id = data.get("user_id")
    group_id = data.get("group_id")
    message = data.get("message", "")
    relay_id = str(uuid.uuid4())[:8]

    _pending[relay_id] = {
        "napcat_ws": napcat_ws,
        "user_id": user_id,
        "group_id": group_id,
    }

    payload = {
        "type": "qq_message",
        "relay_id": relay_id,
        "user_id": user_id,
        "message": message,
    }
    await _st_ws.send(json.dumps(payload, ensure_ascii=False))
    print(f"[relay] 推送 QQ 消息到 ST, relay_id={relay_id}")
    return relay_id


async def request_last_message(napcat_ws, data):
    global _st_ws
    if _st_ws is None:
        print("[relay] 未连接到脚本，无法请求消息")
        return None

    relay_id = str(uuid.uuid4())[:8]
    _pending[relay_id] = {
        "napcat_ws": napcat_ws,
        "user_id": data.get("user_id"),
        "group_id": data.get("group_id"),
    }
    await _st_ws.send(json.dumps({"type": "get_last_message", "relay_id": relay_id}, ensure_ascii=False))
    print(f"[relay] 请求 ST 最近一条消息, relay_id={relay_id}")
    return relay_id


async def handle_st_response(data):
    relay_id = data.get("relay_id")
    content = data.get("content")
    reasoning = data.get("reasoning")
    if relay_id and content:
        await send_to_qq(relay_id, content, reasoning)


async def handle_last_message_response(data):
    relay_id = data.get("relay_id")
    content = data.get("content")
    reasoning = data.get("reasoning")
    if relay_id and content:
        await send_to_qq(relay_id, content, reasoning)


async def send_to_qq(relay_id, content, reasoning_content=None):
    global _last_server_reasoning
    info = _pending.pop(relay_id, None)
    if info is None:
        print(f"[relay] 未找到 relay_id={relay_id} 的待发送记录")
        return

    if not reasoning_content and _last_server_reasoning:
        reasoning_content = _last_server_reasoning
        _last_server_reasoning = None

    napcat_ws = info["napcat_ws"]
    group_id = info.get("group_id")
    user_id = info["user_id"]

    if RENDER_ENABLE:
        if RENDER_INCLUDE_REASONING and reasoning_content:
            img = await render.render_reasoning_to_image(
                reasoning_content, RENDER_OUTPUT_DIR, RENDER_IMAGE_WIDTH
            )
            if img:
                if group_id:
                    await echo.echo_group_image(napcat_ws, group_id, img)
                    print(f"[relay] 思维链图片已发送到群 {group_id}")
                else:
                    await echo.echo_private_image(napcat_ws, user_id, img)
                    print(f"[relay] 思维链图片已发送到私聊, user_id={user_id}")

        if RENDER_IMAGE_THRESHOLD != -1 and len(content) > RENDER_IMAGE_THRESHOLD:
            img = await render.render_to_image(content, RENDER_OUTPUT_DIR, RENDER_IMAGE_WIDTH)
            if img:
                if group_id:
                    await echo.echo_group_image(napcat_ws, group_id, img)
                    print(f"[relay] LLM 回复图片已发送到群 {group_id}")
                else:
                    await echo.echo_private_image(napcat_ws, user_id, img)
                    print(f"[relay] LLM 回复图片已发送到私聊, user_id={user_id}")
                if _processing_relay_id == relay_id:
                    release_lock()
                return

        clean = render.strip_code_blocks(content)
        if group_id:
            await echo.echo_group_msg(napcat_ws, group_id, clean)
            print(f"[relay] LLM 回复已发送到群 {group_id}")
        else:
            await echo.echo_private_msg(napcat_ws, user_id, clean)
            print(f"[relay] LLM 回复已发送到私聊消息, user_id={user_id}")
    else:
        clean = render.strip_code_blocks(content)
        if group_id:
            await echo.echo_group_msg(napcat_ws, group_id, clean)
            print(f"[relay] LLM 回复已发送到群 {group_id}")
        else:
            await echo.echo_private_msg(napcat_ws, user_id, clean)
            print(f"[relay] LLM 回复已发送到私聊消息, user_id={user_id}")

    if _processing_relay_id == relay_id:
        release_lock()
