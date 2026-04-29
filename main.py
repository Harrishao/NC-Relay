import asyncio
import json
import configparser
import websockets
import send


def load_config():
    config = configparser.ConfigParser()
    config.read("config.ini")
    return {
        "port": config.getint("server", "port", fallback=6199),
    }


async def handle(websocket):
    path = websocket.request.path if hasattr(websocket, "request") else "/"
    print(f"[连接] 新客户端连接, 路径: {path}")
    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[原始消息] {raw}")
                continue
            print(f"[收到消息] {json.dumps(data, indent=2, ensure_ascii=False)}")

            if data.get("post_type") == "message" and data.get("message_type") == "private":
                user_id = data.get("user_id")
                message = data.get("message")
                if user_id and message:
                    await send.send_private_msg(websocket, user_id, message)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[断开] 客户端断开: {e}")


async def main():
    config = load_config()
    port = config["port"]
    print(f"[启动] WebSocket 服务监听在 ws://0.0.0.0:{port}")
    async with websockets.serve(handle, "0.0.0.0", port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
