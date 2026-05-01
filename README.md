# NC-Relay2ST

NapCat ↔ SillyTavern 双向消息桥接服务 — 通过 NapCat 接收 QQ 消息，注入酒馆输入框触发 LLM 对话，并将回复实时回传 QQ。

理论上其他支持 OneBot 协议的框架也都可以使用



## 消息流程详解

### NapCat → ST

1. 用户在 QQ 发送 `/st 你好`
2. NapCat 通过反向 WebSocket 推送到 NC-Relay2ST
3. NC-Relay2ST 接收到消息后转发至酒馆助手脚本`sillytavern-nc-relay.js`
4. 脚本通过反向 WebSocket 从 NC-Relay2ST 接收消息，填入酒馆输入框，模拟点击发送按钮
5. NC-Relay2ST 捕获从酒馆发出的消息，转发至配置好的LLM API

### LLM → NapCat

1. 流式响应通过 SSE 逐 chunk 返回给酒馆（酒馆界面内实时显示），同时消息被填入缓存区
2. 完整响应收集完毕后，NC-Relay2ST 拼接消息，形成完整的正文，并发往 NapCat
3. QQ 用户收到完整正文

## 文转图功能

相关设置在`config.ini`中调整

- 设有总开关
- （未实现）文转图可还原浏览器渲染的前端，虽然不能互动
- 可设置超过指定长度的文本转图片发送（设为 -1 则始终发送纯文本），发送纯文本则不附带需渲染的代码块
- 设有思维链返回开关，思维链始终以图片返回

## 快速开始

### 1. 环境要求

- Python 3.8+
- NapCat 或其他支持 OneBot 协议的框架
- SillyTavern 和酒馆助手扩展

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 NapCat 和酒馆助手脚本

- 在 NapCat 建立一个 WebSocket 客户端，地址填`127.0.0.1:6199`，token留空
- 在酒馆助手内导入脚本`nc-relay-st-extension.json`
- 在酒馆中 API 连接配置选 OpenAI 兼容端口，基础 URL 填`http://127.0.0.1:6200`（注意不是https）

#### 3.1 **注意：由于`.json`文件中的端口号是硬写入的，而非从`config.ini`读取，若想自定义端口号，记得连带修改`nc-relay-st-extension.json`中的端口号**

### 4. 配置`config.ini`

`config.ini`中的各项说明:

```ini
[server]
port = 6199            # 你在 NapCat 建立的 WebSocket 客户端端口号
debug = false          # 没用，但可能以后有用，总之别动它

[http]
port = 6200            # 你在酒馆填的端口号

[llm]
base_url = Chovy       # 你的 API base_url，API KEY 由程序从酒馆获取
timeout = 120          # LLM 请求超时 (秒)，不用动它

[admin]
admins = 8884844,<账号2>,<账号3>     # 账号间用英文半角逗号分隔
admin_mode = false     # 启动时管理员模式的默认开关

[render]
enable = true          # 文转图总开关
image_threshold = 0    # 超过该长度的文本转为图片发送，设为 -1 则始终发送纯文本
include_reasoning = false    # 返回思维链开关，思维链始终以图片返回
image_width = 600      # 图片宽度
```

### 5. 启动

```bash
python main.py
```

输出示例：
```
[启动] HTTP 代理服务监听在 http://0.0.0.0:6200
[启动] WebSocket 服务监听在 ws://0.0.0.0:6199  (debug=True)
```

## 命令指南

### 基本操作

- `/st <message>`将消息注入酒馆输入框并模拟点击发送
- `/stop`中止目前的生成命令，酒馆模拟点击停止


### 权限管理

程序设两级管理员，一级管理员账号在`config.ini`中配置，只能从本地修改；  
二级管理员账号在`admin_whitelist.json`中配置，可通过`/admin.add|del <账号>`增删

- `/admin`管理员模式总开关，开启后仅响应白名单成员消息

## 调试

### 控制台日志

NC-Relay2ST 在控制台输出详细日志，前缀标识来源：
- `[NapCat]` — NapCat 连接事件
- `[收到消息]` — 原始 QQ 消息 JSON
- `[relay]` — 消息桥接（推送/回传）
- `[responder]` — 消息过滤分发
- `[echo]` — QQ 消息发送 payload
- `[server]` — HTTP 请求处理

### 请求/响应快照

NC-Relay2ST 将最近一次请求和 LLM 响应分别保存到 `message.json` 和 `response.json`，便于调试。

### 浏览器控制台

酒馆扩展脚本在浏览器 F12 控制台输出 `[NC-Relay]` 前缀日志，包含轮询状态、消息检测、回传确认等信息。

### 还打算加入的功能

- STscript 走不通，准备通过模拟 DOM 点击来实现酒馆界面交互
- 使传回的图片能正常渲染前端 (虽然只是图片不能交互)
- 写一个`/help` list