import json


def parse_sse(raw_bytes):
    """解析 SSE 流式响应，重构为非流式完整响应 JSON"""
    text = raw_bytes.decode("utf-8", errors="replace")
    content_parts = []
    reasoning_parts = []
    last_chunk = None

    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            continue
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        last_chunk = chunk
        choices = chunk.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            if delta.get("content"):
                content_parts.append(delta["content"])
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])

    if last_chunk is None:
        return text

    finish_reason = None
    if last_chunk.get("choices"):
        finish_reason = last_chunk["choices"][0].get("finish_reason")

    message = {"role": "assistant", "content": "".join(content_parts)}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)

    return {
        "id": last_chunk.get("id"),
        "object": last_chunk.get("object", "").replace(".chunk", ""),
        "created": last_chunk.get("created"),
        "model": last_chunk.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": last_chunk.get("usage"),
    }


def extract_content(parsed_response):
    """从解析后的响应中提取 assistant 正文"""
    try:
        return parsed_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
"""
随便写点注释，重新push一次
"""