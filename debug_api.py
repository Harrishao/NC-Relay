"""
ST API 调试工具
用法:
    python debug_api.py                        # 打印所有信息
    python debug_api.py --chats                # 仅最近聊天
    python debug_api.py --chars                # 仅角色卡
    python debug_api.py --char-chats 0         # 角色卡索引0的所有聊天
    python debug_api.py --st-url http://127.0.0.1:8000  # 指定ST地址
"""

import argparse
import json
import re
import sys
import requests


def get_csrf_token(st_url):
    """从ST的/csrf-token接口获取CSRF token"""
    session = requests.Session()
    resp = session.get(f"{st_url.rstrip('/')}/csrf-token", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token", "")
    if token:
        print(f"[调试] 获取到CSRF token: {token[:16]}...")
    else:
        print("[警告] 未获取到CSRF token")
    return token, session


def api_post(st_url, endpoint, csrf_token, session, body=None):
    """向ST API发送POST请求"""
    url = f"{st_url.rstrip('/')}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    resp = session.post(url, headers=headers, json=body or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def print_chars(data):
    """格式化打印角色卡列表"""
    print("\n" + "=" * 70)
    print(f" 角色卡列表 ({len(data)}个)")
    print("=" * 70)
    for i, c in enumerate(data):
        name = c.get("name", "?")
        chat = c.get("chat", "-")
        last = c.get("date_last_chat", 0)
        chat_size = c.get("chat_size", 0)
        last_str = "从未" if last == 0 else _fmt_ts(last)
        size_str = f"{chat_size / 1024:.1f}KB" if chat_size else "0KB"
        print(f"  [{i}] {name:<30s} | 最后活跃: {last_str:<20s} | 聊天: {chat}")
        print(f"      (大小: {size_str})")


def print_recent_chats(data):
    """格式化打印最近聊天列表"""
    print("\n" + "=" * 70)
    print(f" 最近聊天 ({len(data)}个)")
    print("=" * 70)
    for i, c in enumerate(data):
        fname = c.get("file_name", "?")
        items = c.get("chat_items", 0)
        size = c.get("file_size", "?")
        last_mes = c.get("mes", "")
        last_ts = c.get("last_mes", "")
        # 截断最后消息用于显示
        preview = last_mes[:80].replace("\n", " ") + ("..." if len(last_mes) > 80 else "")
        print(f"  [{i}] {fname}")
        print(f"      消息数: {items} | 大小: {size} | 最后: {last_ts}")
        print(f"      预览: {preview}")
        if i < len(data) - 1:
            print()


def print_char_chats(data, char_index):
    """格式化打印指定角色的所有聊天记录"""
    print("\n" + "=" * 70)
    print(f" 角色[{char_index}]的聊天记录 ({len(data)}个)")
    print("=" * 70)
    for i, c in enumerate(data):
        fname = c.get("file_name", "?")
        items = c.get("chat_items", 0)
        size = c.get("file_size", "?")
        last_mes = c.get("mes", "")
        preview = last_mes[:80].replace("\n", " ") + ("..." if len(last_mes) > 80 else "")
        print(f"  [{i}] {fname}")
        print(f"      消息数: {items} | 大小: {size}")
        print(f"      预览: {preview}")
        if i < len(data) - 1:
            print()


def print_raw(data, label=""):
    """原始JSON输出"""
    if label:
        print(f"\n--- {label} ---")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _fmt_ts(ts):
    """格式化时间戳"""
    import datetime
    try:
        dt = datetime.datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def main():
    # 修复Windows控制台编码问题
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="ST API 调试工具")
    parser.add_argument("--st-url", default="http://127.0.0.1:8000", help="SillyTavern URL")
    parser.add_argument("--chats", action="store_true", help="获取最近聊天列表")
    parser.add_argument("--chars", action="store_true", help="获取角色卡列表")
    parser.add_argument("--char-chats", type=int, metavar="INDEX", help="获取指定角色卡索引的所有聊天")
    parser.add_argument("--raw", action="store_true", help="输出原始JSON而非格式化")
    parser.add_argument("--all", action="store_true", help="获取所有信息(默认)")
    args = parser.parse_args()

    # 默认行为：如果没有指定任何command，则--all
    if not any([args.chats, args.chars, args.char_chats is not None, args.all]):
        args.all = True

    st_url = args.st_url

    print(f"[调试] 连接到 {st_url}")

    csrf, session = get_csrf_token(st_url)

    if args.chars or args.all:
        try:
            data = api_post(st_url, "/api/characters/all", csrf, session)
            if args.raw:
                print_raw(data, "角色卡列表")
            else:
                print_chars(data)
        except Exception as e:
            print(f"[错误] 获取角色卡列表失败: {e}")

    if args.chats or args.all:
        try:
            data = api_post(st_url, "/api/chats/recent", csrf, session)
            if args.raw:
                print_raw(data, "最近聊天")
            else:
                print_recent_chats(data)
        except Exception as e:
            print(f"[错误] 获取聊天列表失败: {e}")

    if args.char_chats is not None:
        idx = args.char_chats
        try:
            chars = api_post(st_url, "/api/characters/all", csrf, session)
            if idx >= len(chars):
                print(f"[错误] 角色卡索引 {idx} 超出范围 (共 {len(chars)} 个)")
                sys.exit(1)
            char = chars[idx]
            avatar = char.get("avatar", "")
            print(f"\n[调试] 目标角色: [{idx}] {char.get('name', '?')} (avatar={avatar})")

            data = api_post(st_url, "/api/characters/chats", csrf, session, body={"avatar_url": avatar})
            if args.raw:
                print_raw(data, f"角色[{idx}]的聊天记录")
            else:
                print_char_chats(data, idx)
        except Exception as e:
            print(f"[错误] 获取角色聊天记录失败: {e}")

    print("\n[调试] 完成")


if __name__ == "__main__":
    main()
