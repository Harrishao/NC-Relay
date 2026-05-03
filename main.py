import asyncio
import json
import configparser
import websockets

import admin
import responder
import headless_st


def load_config():
    config = configparser.ConfigParser()
    config.read("config.ini")
    return {
        "port": config.getint("server", "port", fallback=6199),
        "debug": config.getboolean("server", "debug", fallback=False),
    }


async def handle_napcat(websocket, debug):
    print(f"[NapCat] 已连接")
    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[原始消息] {raw}")
                continue
            if debug:
                print(f"[收到消息] {json.dumps(data, indent=2, ensure_ascii=False)}")
            await responder.handle_message(websocket, data)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[NapCat] 断开: {e}")


async def main():
    config = load_config()
    admin.init()
    port = config["port"]
    debug = config["debug"]

    # 启动无头浏览器
    await headless_st.init_browser()

    # WebSocket 服务（仅 NapCat OneBot 连接）
    print(f"[启动] WebSocket 服务监听在 ws://0.0.0.0:{port}  (debug={debug})")

    async def _handle(ws):
        await handle_napcat(ws, debug)

    try:
        async with websockets.serve(_handle, "0.0.0.0", port):
            await asyncio.Future()
    finally:
        await headless_st.close_browser()


if __name__ == "__main__":
    asyncio.run(main())
