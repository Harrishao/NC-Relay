# NC-Relay2ST

NapCat ↔ SillyTavern 双向消息桥接服务 — 通过 NapCat 接收 QQ 消息，以 Playwright 无头浏览器直接操作 SillyTavern 页面触发 LLM 对话，并将 AI 回复以截图形式实时回传 QQ。

理论上其他支持 OneBot v11 协议的框架也可使用。

## 消息流程

```
[QQ 用户] --发送 /st <消息>--> [NapCat]
     --> 反向 WebSocket --> [NC-Relay2ST]
     --> Playwright 在无头浏览器中操作 SillyTavern 页面
         1. 将消息填入 #send_textarea 输入框
         2. 模拟点击 #send_but 发送按钮
         3. 轮询等待 LLM 生成完成（#send_but 重新出现）
         4. 从 JS 上下文读取最后一条 assistant 消息
         5. 截取 .mes 消息容器截图
     --> WebSocket 回传截图 --> [NapCat]
[QQ 用户] <-- 收到 AI 回复截图 <--
```

## 快速开始

### 1. 环境要求

- Python 3.8+
- NapCat 或其他支持 OneBot v11 协议的框架（仅需反向 WebSocket）
- SillyTavern（本地运行，无头浏览器直接操作其 Web 页面）
- Playwright Chromium 浏览器

### 2. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置 NapCat

在 NapCat 中建立一个**反向 WebSocket 客户端**：
- 地址填 `ws://127.0.0.1:6199`
- Token 留空

### 4. 配置 `config.ini`

```ini
[server]
port = 6199              # NapCat WebSocket 客户端连接的端口
debug = false            # 不用管这个，保持 false 就对了

[admin]
admins = <账号>           # 一级管理员账号，多个用英文半角逗号分隔
admin_mode = false       # 启动时管理员模式的默认开关

[headless]
st_url = http://127.0.0.1:8000   # SillyTavern 页面地址
headless = true                  # 是否使用无头模式
viewport_width = 600             # 浏览器视口宽度

[timing]
refresh_delay = 3         # 页面刷新后等待时间（秒）
chat_switch_delay = 2     # 切换聊天后等待时间（秒）
```

### 5. 启动

```bash
python main.py
```

启动后会自动打开浏览器连接 SillyTavern，并启动 WebSocket 服务等待 NapCat 连接。

## 命令指南

### AI 对话

| 命令 | 说明 |
|------|------|
| `/st <消息>` | 将消息注入 ST 输入框，触发 LLM 对话，返回 AI 回复截图 |
| `/stop` | 中止正在进行的 LLM 生成 |
| `/regenerate` | 触发重新生成（等同点击酒馆的重新生成按钮），别名 `/regen` |

### 聊天/角色管理

| 命令 | 说明                              |
|------|---------------------------------|
| `/chat` | 获取最近聊天列表；后续输入数字序号跳转到对应聊天     |
| `/char` | 获取角色卡列表；后续输入数字序号选择对应角色       |
| `/del [1\|2]` | 删除当前聊天最后 1 或 2 条消息 ，无附加参数则默认为 1 |

获取列表后，等待后续输入的窗口为 15 秒，错过输入窗口则返回待命状态。

`/chat `和 `/char` 支持参数传入，如已知列表顺序则无需两次交互。

桌面端QQ输入`/cha`会变成小表情，可以用`/msg`代替`/chat`，作用相同

### 备选回复翻页

翻页按钮仅对最后一条 AI 消息生效，`/right` 在最后一条备选回复时触发重新生成。

| 命令 | 说明 |
|------|------|
| `/left` | 切换到上一个备选回复 |
| `/right` | 切换到下一个备选回复 |

### 截图

| 命令 | 说明 |
|------|------|
| `/lastmsg` | 获取最后一条消息的截图 |
| `/ss` | 获取 ST 全页截图 |
| `/rf` | 刷新 ST 页面 |

### 权限管理

程序设两级管理员：

- **L1（一级管理员）**：在 `config.ini` 中配置，只能从本地修改
- **L2（二级管理员/白名单）**：存储在 `admin_whitelist.json` 中，可通过命令动态管理

| 命令                | 说明 |
|-------------------|------|
| `/admin`          | 管理员模式总开关，开启后仅响应白名单成员消息 |
| `/admin.add <账号>` | 添加二级管理员 |
| `/admin.del <账号>` | 删除二级管理员 |

## 调试

### 控制台日志

日志前缀标识来源：
- `[NapCat]` — NapCat 连接/断开事件
- `[收到消息]` — 原始 QQ 消息
- `[responder]` — 消息过滤与命令分发
- `[headless]` — 无头浏览器操作
- `[echo]` — QQ 消息发送

### 请求/响应快照

最近一次 LLM 请求和响应分别保存到 `message.json` 和 `response.json`。
