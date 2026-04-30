import json
import os
import time
import configparser
from aiohttp import web, ClientSession, ClientTimeout

import llm
import relay

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, "config.ini"))

LLM_BASE_URL = config.get("llm", "base_url", fallback="https://api.deepseek.com/beta")
LLM_TIMEOUT = config.getint("llm", "timeout", fallback=120)
WS_PORT = config.getint("server", "port", fallback=6199)
HTTP_PORT = config.getint("http", "port", fallback=6200)

MESSAGE_FILE = os.path.join(BASE_DIR, "message.json")
RESPONSE_FILE = os.path.join(BASE_DIR, "response.json")

EXCLUDED_REQ_HEADERS = {"host", "connection", "content-length", "transfer-encoding"}
EXCLUDED_RES_HEADERS = {
    "host", "connection", "content-length", "transfer-encoding", "content-encoding",
}


def _get_relay_id(request, body_data):
    """从请求中提取 relay_id，支持 query / header / body 三种方式"""
    relay_id = request.query.get("nc_relay_id")
    if relay_id:
        return relay_id
    relay_id = request.headers.get("X-NC-Relay-Id")
    if relay_id:
        return relay_id
    if isinstance(body_data, dict):
        meta = body_data.get("nc_relay_meta", {})
        if isinstance(meta, dict):
            return meta.get("relay_id")
    return None


def save_message(body_data):
    record = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "body": body_data,
    }
    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"[server] 消息已保存到 {MESSAGE_FILE}")


def save_response(parsed):
    record = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "body": parsed,
    }
    with open(RESPONSE_FILE, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"[server] 响应已保存到 {RESPONSE_FILE}")


async def handle_chat_completions(request):
    llm_url = f"{LLM_BASE_URL}/chat/completions"

    req_headers = {}
    for key, value in request.headers.items():
        if key.lower() not in EXCLUDED_REQ_HEADERS:
            req_headers[key] = value

    body_bytes = await request.read()
    try:
        body_data = json.loads(body_bytes)
    except json.JSONDecodeError:
        body_data = body_bytes.decode("utf-8", errors="replace")

    relay_id = _get_relay_id(request, body_data)
    save_message(body_data)

    if isinstance(body_data, dict):
        body_data.pop("nc_relay_meta", None)
        body_bytes = json.dumps(body_data, ensure_ascii=False).encode("utf-8")

    is_stream = isinstance(body_data, dict) and body_data.get("stream", False)

    timeout = ClientTimeout(total=LLM_TIMEOUT)
    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.post(llm_url, headers=req_headers, data=body_bytes) as llm_resp:
                res_headers = {}
                for key, value in llm_resp.headers.items():
                    if key.lower() not in EXCLUDED_RES_HEADERS:
                        res_headers[key] = value
                content_type = llm_resp.headers.get("Content-Type", "")

                if is_stream or "text/event-stream" in content_type:
                    resp = web.StreamResponse(status=llm_resp.status, headers=res_headers)
                    await resp.prepare(request)

                    chunks = []
                    async for chunk in llm_resp.content.iter_any():
                        if chunk:
                            chunks.append(chunk)
                            await resp.write(chunk)
                    await resp.write_eof()

                    full_body = b"".join(chunks)
                    parsed = llm.parse_sse(full_body)
                    save_response(parsed)
                    content = llm.extract_content(parsed)
                    if relay_id and content:
                        await relay.send_to_qq(relay_id, content)

                    return resp
                else:
                    resp_body = await llm_resp.read()
                    try:
                        parsed = json.loads(resp_body)
                    except json.JSONDecodeError:
                        parsed = resp_body.decode("utf-8", errors="replace")
                    save_response(parsed)

                    content = llm.extract_content(parsed) if isinstance(parsed, dict) else None
                    if relay_id and content:
                        await relay.send_to_qq(relay_id, content)

                    return web.Response(
                        body=resp_body,
                        status=llm_resp.status,
                        headers=res_headers,
                        content_type=content_type,
                    )
    except Exception as e:
        print(f"[server] LLM 请求失败: {e}")
        return web.Response(text=f"Upstream request failed: {e}", status=502)


def _inject_ports(filepath, content_type):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("__NC_WS_PORT__", str(WS_PORT))
    content = content.replace("__NC_HTTP_PORT__", str(HTTP_PORT))
    return web.Response(text=content, content_type=content_type, headers={
        "Access-Control-Allow-Origin": "*",
    })


async def serve_extension_js(request):
    js_path = os.path.join(BASE_DIR, "sillytavern-nc-relay.js")
    return _inject_ports(js_path, "application/javascript; charset=utf-8")


async def serve_extension_json(request):
    json_path = os.path.join(BASE_DIR, "nc-relay-st-extension.json")
    return _inject_ports(json_path, "application/json; charset=utf-8")


def create_app():
    app = web.Application()
    app.router.add_post("/chat/completions", handle_chat_completions)
    app.router.add_get("/nc-relay.js", serve_extension_js)
    app.router.add_get("/nc-relay-st-extension.json", serve_extension_json)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    return app
