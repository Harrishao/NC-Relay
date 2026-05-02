import relay
import admin
import echo

_CMDS = {
    "/st":         "_cmd_st",
    "/stop":       "_cmd_stop",
    "/lastmsg":    "_cmd_lastmsg",
    "/admin":      "_cmd_admin",
    "/admin.add":  "_cmd_admin_add",
    "/admin.del":  "_cmd_admin_del",
}


def _extract_text(message):
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                parts.append(seg.get("data", {}).get("text", ""))
        return "".join(parts)
    return str(message or "")


def _parse_command(message):
    text = _extract_text(message).strip()
    for cmd in sorted(_CMDS, key=len, reverse=True):
        if text == cmd:
            return _CMDS[cmd], ""
        if text.startswith(cmd + " "):
            return _CMDS[cmd], text[len(cmd):].strip()
    return None, None


async def _reply(websocket, data, text):
    msg_type = data.get("message_type")
    if msg_type == "group":
        group_id = data.get("group_id")
        if group_id:
            await echo.echo_group_msg(websocket, group_id, text)
            return
    user_id = data.get("user_id")
    if user_id:
        await echo.echo_private_msg(websocket, user_id, text)


async def _cmd_st(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    if relay.is_locked():
        await _reply(websocket, data, "有处理中的消息，等一会吧...或者使用/stop 中止？")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    if not data.get("user_id") or not data.get("message"):
        return

    relay_id = await relay.push_to_st(websocket, data)
    if relay_id:
        relay.acquire_lock(relay_id)


async def _cmd_stop(websocket, data, args):
    cancelled = await relay.cancel_processing()
    if cancelled:
        await _reply(websocket, data, "消息处理中止了哦")
    else:
        await _reply(websocket, data, "没有要终止的消息哦")


async def _cmd_admin(websocket, data, args):
    user_id = str(data.get("user_id", ""))
    if not admin.is_l1_admin(user_id):
        return
    new_state = admin.toggle_admin_mode()
    state_str = "开启" if new_state else "关闭"
    await _reply(websocket, data, f"收到，已{state_str}管理员模式")


async def _cmd_admin_add(websocket, data, args):
    user_id = str(data.get("user_id", ""))
    if not admin.is_l1_admin(user_id):
        return
    target = args.strip()
    if not target:
        await _reply(websocket, data, "用法: /admin.add <QQ号>")
        return
    admin.add_whitelist(target)
    await _reply(websocket, data, f"将 {target} 加入白名单了哦")


async def _cmd_admin_del(websocket, data, args):
    user_id = str(data.get("user_id", ""))
    if not admin.is_l1_admin(user_id):
        return
    target = args.strip()
    if not target:
        await _reply(websocket, data, "用法: /admin.del <QQ号>")
        return
    admin.remove_whitelist(target)
    await _reply(websocket, data, f" {target} 被移出白名单了哦")


async def _cmd_lastmsg(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    relay_id = await relay.request_last_message(websocket, data)
    if relay_id is None:
        await _reply(websocket, data, "尚未连接到酒馆，暂时无法获取消息。")


_CMD_HANDLERS = {
    "_cmd_st":        _cmd_st,
    "_cmd_stop":      _cmd_stop,
    "_cmd_lastmsg":   _cmd_lastmsg,
    "_cmd_admin":     _cmd_admin,
    "_cmd_admin_add": _cmd_admin_add,
    "_cmd_admin_del": _cmd_admin_del,
}


async def handle_message(websocket, data):
    if data.get("post_type") != "message":
        return

    cmd_func_name, args = _parse_command(data.get("message", ""))
    if cmd_func_name is None:
        return

    handler = _CMD_HANDLERS[cmd_func_name]
    await handler(websocket, data, args)
