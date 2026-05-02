import asyncio
import json
import configparser
import websockets
from aiohttp import web

import admin
import responder
import relay
import server


def load_config():
    config = configparser.ConfigParser()
    config.read("config.ini")
    return {
        "port": config.getint("server", "port", fallback=6199),
        "http_port": config.getint("http", "port", fallback=6200),
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


async def handle_st_extension(websocket):
    relay.register_st(websocket)
    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
                msg_type = data.get("type")
                if msg_type == "st_response":
                    await relay.handle_st_response(data)
                elif msg_type == "last_message":
                    await relay.handle_last_message_response(data)
            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        relay.unregister_st(websocket)


async def handle_ws(websocket, debug):
    path = websocket.request.path if hasattr(websocket, "request") else "/"
    print(f"[连接] 新客户端, 路径: {path}")
    if path == "/st":
        await handle_st_extension(websocket)
    else:
        await handle_napcat(websocket, debug)


async def main():
    config = load_config()
    admin.init()
    port = config["port"]
    http_port = config["http_port"]
    debug = config["debug"]

    # HTTP 代理服务
    app = server.create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", http_port)
    await site.start()
    print(f"[启动] HTTP 代理服务监听在 http://0.0.0.0:{http_port}")

    # WebSocket 服务
    print(f"[启动] WebSocket 服务监听在 ws://0.0.0.0:{port}  (debug={debug})")
    async def _handle(ws):
        await handle_ws(ws, debug)

    async with websockets.serve(_handle, "0.0.0.0", port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
