import asyncio
import configparser
import datetime
import os
import re
import time
import uuid
import headless_st
import admin
import echo
import render

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_config = configparser.ConfigParser()
_config.read(os.path.join(BASE_DIR, "config.ini"))
CHAT_SWITCH_DELAY = _config.getint("timing", "chat_switch_delay", fallback=3)

_CMDS = {
    "/st":         "_cmd_st",
    "/stop":       "_cmd_stop",
    "/lastmsg":    "_cmd_lastmsg",
    "/ss":         "_cmd_ss",
    "/rf":         "_cmd_rf",
    "/chat":       "_cmd_chat",
    "/msg":        "_cmd_chat",
    "/char":       "_cmd_char",
    "/del":        "_cmd_del",
    "/left":       "_cmd_left",
    "/right":      "_cmd_right",
    "/admin":      "_cmd_admin",
    "/admin.add":  "_cmd_admin_add",
    "/admin.del":  "_cmd_admin_del",
}

# 待处理交互状态 {user_id: {action, data, group_id, websocket, expires_at}}
_pending = {}
PENDING_TIMEOUT = 15


def _set_pending(user_id, action, data, websocket, group_id):
    _pending[user_id] = {
        "action": action,
        "data": data,
        "websocket": websocket,
        "group_id": group_id,
        "expires_at": time.time() + PENDING_TIMEOUT,
    }


def _get_pending(user_id):
    p = _pending.get(user_id)
    if not p:
        return None
    if time.time() > p["expires_at"]:
        del _pending[user_id]
        return None
    return p


def _clear_pending(user_id):
    _pending.pop(user_id, None)


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

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    if not data.get("user_id") or not data.get("message"):
        return

    group_id = data.get("group_id")
    relay_id = str(uuid.uuid4())[:8]

    if not headless_st.acquire_lock(relay_id):
        await _reply(websocket, data, "有处理中的消息，等一会吧...或者使用/stop 中止？")
        return

    try:
        text = _extract_text(data["message"])
        ok = await headless_st.inject_message(text, relay_id)
        if not ok:
            await _reply(websocket, data, "消息注入失败，请稍后重试...")
            return

        response = await headless_st.wait_for_response(relay_id)
        if not response:
            await _reply(websocket, data, "等待LLM回复超时，请稍后重试...")
            return

        content = response["content"]

        # 截屏发送图片
        img = await headless_st.capture_screenshot()
        if img:
            if group_id:
                await echo.echo_group_image(websocket, group_id, img)
                print(f"[responder] 截图已发送到群 {group_id}")
            else:
                await echo.echo_private_image(websocket, user_id, img)
                print(f"[responder] 截图已发送到私聊, user_id={user_id}")
        else:
            # 截屏失败时回退文本
            clean = content[:500]
            if group_id:
                await echo.echo_group_msg(websocket, group_id, clean)
            else:
                await echo.echo_private_msg(websocket, user_id, clean)
    finally:
        headless_st.release_lock()


async def _cmd_stop(websocket, data, args):
    cancelled = await headless_st.cancel_processing()
    if cancelled:
        await _reply(websocket, data, "消息处理中止了哦")
    else:
        await _reply(websocket, data, "没有要终止的消息哦")


async def _cmd_lastmsg(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    img = await headless_st.capture_screenshot()
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 最后消息截图已发送, user_id={user_id}")
    else:
        await _reply(websocket, data, "截图失败，请稍后重试...")


async def _cmd_del(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    n = 1
    if args.strip() in ("1", "2"):
        n = int(args.strip())

    ok = await headless_st.delete_messages(n)
    if not ok:
        await _reply(websocket, data, "删除消息失败。")
        return

    await asyncio.sleep(1)
    img = await headless_st.capture_screenshot()
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 删除确认截图已发送, user_id={user_id}")
    else:
        await _reply(websocket, data, f"已删除 {n} 条消息。")


async def _cmd_left(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    ok = await headless_st.swipe_left()
    if not ok:
        await _reply(websocket, data, "左翻页失败，没有更多备选回复或当前不在聊天中。")
        return

    img = await headless_st.capture_screenshot()
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 左翻页截图已发送, user_id={user_id}")
    else:
        await _reply(websocket, data, "截图失败，请稍后重试...")


async def _cmd_right(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")
    relay_id = str(uuid.uuid4())[:8]

    result = await headless_st.swipe_right()
    if result is None:
        await _reply(websocket, data, "右翻页失败，当前不在聊天中。")
        return

    # 如果触发了新生成，需要等待LLM完成
    if result == "generating":
        response = await headless_st.wait_for_response(relay_id)
        if not response:
            await _reply(websocket, data, "等待LLM回复超时...")
            return

    img = await headless_st.capture_screenshot()
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 右翻页截图已发送, user_id={user_id}")
    else:
        await _reply(websocket, data, "截图失败，请稍后重试...")


async def _cmd_ss(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    img = await headless_st.capture_full_screenshot()
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 全页截图已发送, user_id={user_id}")
    else:
        await _reply(websocket, data, "截图失败，请稍后重试...")


async def _cmd_rf(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    ok = await headless_st.refresh_page()
    if not ok:
        await _reply(websocket, data, "页面刷新失败，请稍后重试...")
        return

    img = await headless_st.capture_full_screenshot()
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 刷新后截图已发送, user_id={user_id}")
    else:
        await _reply(websocket, data, "刷新成功但截图失败...")


async def _cmd_chat(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    chats = await headless_st.fetch_recent_chats()
    if not chats:
        await _reply(websocket, data, "获取聊天列表失败。")
        return

    # 格式化markdown — 用blockquote保持视觉层次
    lines = [f"# 最近聊天 ({len(chats)}条)", ""]
    for i, c in enumerate(chats):
        ch_name = c.get("file_name", "?").replace(".jsonl", "")
        items = c.get("chat_items", 0)
        size = c.get("file_size", "?")
        # 截取最后消息预览（彻底清理markdown/HTML破坏性字符）
        mes = c.get("mes", "")
        # 去掉HTML标签
        mes = re.sub(r'<[^>]+>', '', mes)
        # 去掉代码块 ```...```
        mes = re.sub(r'```[\s\S]*?```', '', mes)
        # 去掉行内代码 `
        mes = mes.replace("`", "'")
        # 转为单行
        mes = mes.replace("\n", " ").replace("\r", " ")
        # 转义残余markdown特殊字符（先\\再*_#>）
        mes = mes.replace("\\", "\\\\")
        mes = mes.replace("*", "\\*").replace("_", "\\_")
        mes = mes.replace("#", "\\#").replace(">", "\\>")
        # 合并多余空格
        mes = re.sub(r'\s{2,}', ' ', mes).strip()
        preview = mes[:60] + ("..." if len(mes) > 60 else "")
        lines.append(f"**{i}** — {ch_name}")
        lines.append(f"> 消息: {items} | 大小: {size}")
        lines.append(f"> {preview}")
        lines.append("")

    md = "\n".join(lines)
    img = await render.render_to_image(md, headless_st.RENDER_OUTPUT_DIR)
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 聊天列表已发送, user_id={user_id}")

    _set_pending(user_id, "chat_pick", chats, websocket, group_id)


async def _cmd_char(websocket, data, args):
    user_id = str(data.get("user_id", ""))

    if not admin.is_whitelisted(user_id):
        await _reply(websocket, data, "管理员模式已开启，可是你不在白名单哦...")
        return

    msg_type = data.get("message_type")
    if msg_type not in ("private", "group"):
        return

    group_id = data.get("group_id")

    chars = await headless_st.fetch_characters()
    if not chars:
        await _reply(websocket, data, "获取角色卡列表失败。")
        return

    # 格式化markdown
    lines = [f"# 角色卡列表 ({len(chars)}个)", ""]
    for i, c in enumerate(chars):
        c_name = c.get("name", "?")
        last = c.get("date_last_chat", 0)
        if last == 0:
            last_str = "从未"
        else:
            try:
                dt = datetime.datetime.fromtimestamp(last / 1000)
                last_str = dt.strftime("%m/%d %H:%M")
            except Exception:
                last_str = str(last)
        lines.append(f"**{i}** — {c_name}  _(最后: {last_str})_")

    md = "\n".join(lines)
    img = await render.render_to_image(md, headless_st.RENDER_OUTPUT_DIR)
    if img:
        if group_id:
            await echo.echo_group_image(websocket, group_id, img)
        else:
            await echo.echo_private_image(websocket, user_id, img)
        print(f"[responder] 角色卡列表已发送, user_id={user_id}")

    _set_pending(user_id, "char_pick", chars, websocket, group_id)


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


_CMD_HANDLERS = {
    "_cmd_st":        _cmd_st,
    "_cmd_stop":      _cmd_stop,
    "_cmd_lastmsg":   _cmd_lastmsg,
    "_cmd_ss":        _cmd_ss,
    "_cmd_rf":        _cmd_rf,
    "_cmd_chat":      _cmd_chat,
    "_cmd_char":      _cmd_char,
    "_cmd_del":       _cmd_del,
    "_cmd_left":      _cmd_left,
    "_cmd_right":     _cmd_right,
    "_cmd_admin":     _cmd_admin,
    "_cmd_admin_add": _cmd_admin_add,
    "_cmd_admin_del": _cmd_admin_del,
}


async def _handle_pending(websocket, data, pending, raw_text):
    """处理待处理交互的后续输入"""
    action = pending["action"]
    p_data = pending["data"]
    group_id = pending["group_id"]

    # 特殊处理确认状态
    if action == "chat_delete_confirm":
        if raw_text.strip().lower() == "y":
            file_name = p_data["file_name"]
            ok = await headless_st.delete_chat(file_name)
            if not ok:
                await _reply(websocket, data, "删除聊天失败。")
            else:
                # 删除后返回更新后的聊天列表
                chats = await headless_st.fetch_recent_chats()
                if chats:
                    lines = [f"# 最近聊天 ({len(chats)}条) - 已删除", ""]
                    for i, c in enumerate(chats):
                        ch_name = c.get("file_name", "?").replace(".jsonl", "")
                        items = c.get("chat_items", 0)
                        size = c.get("file_size", "?")
                        lines.append(f"**{i}** — {ch_name}")
                        lines.append(f"> 消息: {items} | 大小: {size}")
                        lines.append("")
                    md = "\n".join(lines)
                    img = await render.render_to_image(md, headless_st.RENDER_OUTPUT_DIR)
                    if img:
                        if group_id:
                            await echo.echo_group_image(websocket, group_id, img)
                        else:
                            await echo.echo_private_image(websocket, str(data.get("user_id", "")), img)
                    _set_pending(str(data.get("user_id", "")), "chat_pick", chats, websocket, group_id)
                else:
                    await _reply(websocket, data, "已删除，但获取聊天列表失败。")
                    _clear_pending(str(data.get("user_id", "")))
        else:
            await _reply(websocket, data, "已取消删除，返回待命状态。")
        _clear_pending(str(data.get("user_id", "")))
        return

    # chat_pick 状态下 del <数字> → 删除整个聊天
    if action == "chat_pick":
        m = re.match(r'^del\s+(\d+)$', raw_text.strip(), re.IGNORECASE)
        if m:
            index = int(m.group(1))
            chats = p_data
            if index < 0 or index >= len(chats):
                await _reply(websocket, data, "序号超出范围，已返回待命状态。")
                _clear_pending(str(data.get("user_id", "")))
                return
            chat = chats[index]
            ch_name = chat.get("file_name", "?").replace(".jsonl", "")
            await _reply(websocket, data, f"确认删除 {ch_name} ? 回复 y 确认，其他键取消。(15秒)")
            _set_pending(str(data.get("user_id", "")), "chat_delete_confirm",
                         {"file_name": chat.get("file_name", "")}, websocket, group_id)
            return

    # 解析数字
    try:
        index = int(raw_text.strip())
    except (ValueError, TypeError):
        await _reply(websocket, data, "类型错误，请输入数字序号。已返回待命状态。")
        _clear_pending(str(data.get("user_id", "")))
        return

    if action == "chat_pick":
        # 从聊天列表中选择
        chats = p_data
        if index < 0 or index >= len(chats):
            await _reply(websocket, data, "序号超出范围，已返回待命状态。")
            _clear_pending(str(data.get("user_id", "")))
            return

        chat = chats[index]
        file_name = chat.get("file_name", "")
        if not file_name:
            await _reply(websocket, data, "无法获取聊天文件名，已返回待命状态。")
            _clear_pending(str(data.get("user_id", "")))
            return

        ok = await headless_st.open_chat(file_name)
        if not ok:
            await _reply(websocket, data, "切换聊天失败，请稍后重试。")
            _clear_pending(str(data.get("user_id", "")))
            return

        # 截图确认（最后一条消息元素）
        await asyncio.sleep(CHAT_SWITCH_DELAY)  # 等待ST加载聊天
        img = await headless_st.capture_screenshot()
        if img:
            if group_id:
                await echo.echo_group_image(websocket, group_id, img)
            else:
                await echo.echo_private_image(websocket, str(data.get("user_id", "")), img)
            print(f"[responder] 聊天切换确认截图已发送")
        _clear_pending(str(data.get("user_id", "")))

    elif action == "char_pick":
        # 从角色卡列表中选择
        chars = p_data
        if index < 0 or index >= len(chars):
            await _reply(websocket, data, "序号超出范围，已返回待命状态。")
            _clear_pending(str(data.get("user_id", "")))
            return

        char = chars[index]
        avatar = char.get("avatar", "")
        char_name = char.get("name", "?")

        chats = await headless_st.fetch_character_chats(avatar)
        if not chats:
            await _reply(websocket, data, f"角色[{char_name}]没有聊天记录。")
            _clear_pending(str(data.get("user_id", "")))
            return

        if len(chats) == 1:
            # 仅一条，直接跳转
            file_name = chats[0].get("file_name", "")
            if not file_name:
                await _reply(websocket, data, "无法获取聊天文件名。")
                _clear_pending(str(data.get("user_id", "")))
                return

            ok = await headless_st.open_chat(file_name)
            if not ok:
                await _reply(websocket, data, "切换聊天失败。")
                _clear_pending(str(data.get("user_id", "")))
                return

            await asyncio.sleep(CHAT_SWITCH_DELAY)
            img = await headless_st.capture_screenshot()
            if img:
                if group_id:
                    await echo.echo_group_image(websocket, group_id, img)
                else:
                    await echo.echo_private_image(websocket, str(data.get("user_id", "")), img)
            _clear_pending(str(data.get("user_id", "")))
        else:
            # 多条，返回列表图片等待进一步选择
            lines = [f"# {char_name} 的聊天记录 ({len(chats)}条)", ""]
            for i, c in enumerate(chats):
                fname = c.get("file_name", "?").replace(".jsonl", "")
                items = c.get("chat_items", 0)
                size = c.get("file_size", "?")
                lines.append(f"**{i}** — {fname}")
                lines.append(f"> 消息: {items} | 大小: {size}")
                lines.append("")

            md = "\n".join(lines)
            img = await render.render_to_image(md, headless_st.RENDER_OUTPUT_DIR)
            if img:
                if group_id:
                    await echo.echo_group_image(websocket, group_id, img)
                else:
                    await echo.echo_private_image(websocket, str(data.get("user_id", "")), img)

            user_id = str(data.get("user_id", ""))
            _set_pending(user_id, "chat_pick_for_char", chats, websocket, group_id)
            print(f"[responder] 等待用户选择 {char_name} 的聊天记录...")

    elif action == "chat_pick_for_char":
        # 从指定角色的聊天列表中选择
        chats = p_data
        if index < 0 or index >= len(chats):
            await _reply(websocket, data, "序号超出范围，已返回待命状态。")
            _clear_pending(str(data.get("user_id", "")))
            return

        chat = chats[index]
        file_name = chat.get("file_name", "")
        if not file_name:
            await _reply(websocket, data, "无法获取聊天文件名。")
            _clear_pending(str(data.get("user_id", "")))
            return

        ok = await headless_st.open_chat(file_name)
        if not ok:
            await _reply(websocket, data, "切换聊天失败。")
            _clear_pending(str(data.get("user_id", "")))
            return

        await asyncio.sleep(CHAT_SWITCH_DELAY)
        img = await headless_st.capture_screenshot()
        if img:
            if group_id:
                await echo.echo_group_image(websocket, group_id, img)
            else:
                await echo.echo_private_image(websocket, str(data.get("user_id", "")), img)
            print(f"[responder] 聊天切换确认截图已发送")
        _clear_pending(str(data.get("user_id", "")))


async def handle_message(websocket, data):
    if data.get("post_type") != "message":
        return

    user_id = str(data.get("user_id", ""))
    raw_text = _extract_text(data.get("message", ""))

    # 检查pending状态
    pending = _get_pending(user_id)
    if pending:
        raw = raw_text.strip()

        # 确认状态：处理 y/n
        if pending["action"] == "chat_delete_confirm":
            if raw.lower() == "y":
                await _handle_pending(websocket, data, pending, "y")
            else:
                await _reply(websocket, data, "已取消删除，返回待命状态。")
                _clear_pending(user_id)
            return

        # chat_pick状态下del <数字> → 删除整个聊天
        if pending["action"] == "chat_pick":
            m = re.match(r'^del\s+(\d+)$', raw, re.IGNORECASE)
            if m:
                await _handle_pending(websocket, data, pending, raw)
                return

        # 数字 → 选择逻辑
        if raw.isdigit():
            await _handle_pending(websocket, data, pending, raw)
            return

        # 新命令 → 清除pending走正常流程
        if raw.startswith("/"):
            _clear_pending(user_id)
        else:
            # 类型错误
            await _reply(websocket, data, "类型错误，请输入数字序号。已返回待命状态。")
            _clear_pending(user_id)
            return

    cmd_func_name, args = _parse_command(data.get("message", ""))
    if cmd_func_name is None:
        return

    handler = _CMD_HANDLERS[cmd_func_name]
    await handler(websocket, data, args)
