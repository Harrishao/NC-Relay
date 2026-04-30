// NC-Relay2ST bridge for SillyTavern
// 由 NC-Relay2ST HTTP 服务提供, 通过 ST 插件脚本 import 加载

(function () {
    "use strict";

    var NC_RELAY_WS_URL = "ws://localhost:__NC_WS_PORT__/st";
    var topWin = window.parent || window;
    var topDoc = topWin.document;

    function notify(msg, type) {
        console.log("[NC-Relay2ST] " + msg);
        try {
            if (topWin.toastr) {
                topWin.toastr[type || "info"](msg, "NC-Relay2ST");
            }
        } catch (_) {}
    }

    notify("扩展脚本已加载");

    function getST() {
        return topWin.SillyTavern || window.SillyTavern || (window.top && window.top.SillyTavern);
    }

    var ws = null;
    var reconnectTimer = null;
    var pendingRelayId = null;
    var lastChatLength = 0;
    var lastMesLen = 0;
    var stableCount = 0;
    var pollTimer = null;
    var pollCount = 0;

    function connect() {
        if (ws && ws.readyState === WebSocket.OPEN) return;

        ws = new WebSocket(NC_RELAY_WS_URL);

        ws.onopen = function () {
            console.log("[NC-Relay2ST] ST扩展已连接");
            notify("NC-Relay2ST QQ桥接已连接", "success");
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);
                if (data.type === "qq_message") {
                    handleQQMessage(data);
                } else if (data.type === "stop") {
                    handleStopMessage(data);
                }
            } catch (e) {
                console.error("[NC-Relay2ST] 消息解析失败:", e);
            }
        };

        ws.onclose = function () {
            console.log("[NC-Relay2ST] WebSocket断开, 5秒后重连");
            reconnectTimer = setTimeout(connect, 5000);
        };

        ws.onerror = function () {
            console.error("[NC-Relay2ST] WebSocket错误");
        };
    }

    function extractText(message) {
        if (typeof message === "string") return message;
        if (Array.isArray(message)) {
            var parts = [];
            for (var i = 0; i < message.length; i++) {
                var seg = message[i];
                if (seg.type === "text" && seg.data && seg.data.text) {
                    parts.push(seg.data.text);
                }
            }
            return parts.join("");
        }
        return String(message || "");
    }

    function handleQQMessage(data) {
        var relay_id = data.relay_id;
        var rawMessage = data.message;
        var message = extractText(rawMessage);
        console.log("[NC-Relay2ST] 收到QQ消息: " + message + " (relay_id=" + relay_id + ")");

        pendingRelayId = relay_id;
        pollCount = 0;
        lastMesLen = 0;
        stableCount = 0;

        // 记录当前聊天长度，用于检测新回复
        var ctx = getST() && getST().getContext();
        lastChatLength = (ctx && ctx.chat) ? ctx.chat.length : 0;
        console.log("[NC-Relay2ST] lastChatLength=" + lastChatLength + ", ST found=" + !!getST());

        // 去掉 /st 前缀
        var cleanMessage = message.replace(/^\/st\s*/, "");

        // 填入 ST 输入框（使用原生 DOM API + 触发 input 事件）
        var textarea = topDoc.getElementById("send_textarea");
        if (!textarea) {
            console.error("[NC-Relay2ST] 找不到 #send_textarea");
            return;
        }

        // 用原生 setter 设置值，确保 React/Vue 等框架能感知
        var nativeSetter = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype, "value"
        );
        if (nativeSetter && nativeSetter.set) {
            nativeSetter.set.call(textarea, cleanMessage);
        } else {
            textarea.value = cleanMessage;
        }
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        textarea.dispatchEvent(new Event("change", { bubbles: true }));

        console.log("[NC-Relay2ST] 已填入输入框: " + cleanMessage);

        // 触发发送按钮
        var sendBtn = topDoc.getElementById("send_but");
        if (sendBtn) {
            sendBtn.click();
            console.log("[NC-Relay2ST] 已触发发送");
        } else {
            console.error("[NC-Relay2ST] 找不到 #send_but");
        }

        // 轮询等待 LLM 回复
        startPolling();
    }

    function handleStopMessage(data) {
        console.log("[NC-Relay2ST] 收到停止指令, relay_id=" + data.relay_id);
        if (pendingRelayId === data.relay_id) {
            pendingRelayId = null;
            stopPolling();
            lastMesLen = 0;
            stableCount = 0;
            pollCount = 0;

            // 点击酒馆的中止按钮停止 LLM 生成
            var stopBtn = topDoc.getElementById("mes_stop");
            if (stopBtn) {
                stopBtn.click();
                console.log("[NC-Relay2ST] 已触发酒馆中止按钮");
            }

            notify("QQ消息处理已停止", "warning");
        }
    }

    function startPolling() {
        stopPolling();
        pollTimer = setInterval(captureAndReply, 500);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function captureAndReply() {
        if (!pendingRelayId) {
            stopPolling();
            return;
        }

        pollCount++;
        if (pollCount > 240) {
            console.error("[NC-Relay2ST] 轮询超时, 放弃 relay_id=" + pendingRelayId);
            pendingRelayId = null;
            stopPolling();
            return;
        }

        var st = getST();
        var ctx = st && st.getContext();

        if (pollCount <= 3 || pollCount % 10 === 0) {
            console.log("[NC-Relay2ST] 轮询#" + pollCount + " st=" + !!st + " ctx=" + !!ctx
                + " chatLen=" + (ctx && ctx.chat ? ctx.chat.length : "?")
                + " last=" + lastChatLength);
        }

        if (!ctx || !ctx.chat) return;

        var messages = ctx.chat;
        if (messages.length <= lastChatLength) return;

        // 找到了新消息
        console.log("[NC-Relay2ST] 检测到新消息! chatLen " + lastChatLength + " -> " + messages.length);
        for (var i = lastChatLength; i < messages.length; i++) {
            console.log("[NC-Relay2ST]  msg[" + i + "] is_user=" + messages[i].is_user + " is_system=" + messages[i].is_system + " mes_len=" + (messages[i].mes ? messages[i].mes.length : 0));
        }

        // 找最新一条 assistant 消息并等流式结束（mes 长度连续 4 轮不变）
        for (var i = messages.length - 1; i >= lastChatLength; i--) {
            var msg = messages[i];
            if (msg && !msg.is_user && !msg.is_system && msg.mes) {
                var currentLen = msg.mes.length;
                if (currentLen === lastMesLen) {
                    stableCount++;
                    if (stableCount >= 4) {
                        var relayId = pendingRelayId;
                        pendingRelayId = null;
                        lastMesLen = 0;
                        stableCount = 0;
                        stopPolling();

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: "st_response",
                                relay_id: relayId,
                                content: msg.mes,
                            }));
                            console.log("[NC-Relay2ST] 回复已回传, relay_id=" + relayId + " len=" + currentLen);
                        } else {
                            console.error("[NC-Relay2ST] ws不可用, readyState=" + (ws ? ws.readyState : "null"));
                        }
                    }
                } else {
                    lastMesLen = currentLen;
                    stableCount = 0;
                }
                return;
            }
        }
    }

    // 初始化
    console.log("[NC-Relay2ST] 扩展已加载");
    connect();
})();
