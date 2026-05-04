"""
无头浏览器直连 SillyTavern 模块
通过 Playwright 在无头 Chromium 中操作 ST 页面、注入消息、捕获回复并截屏
"""

import os
import re
import asyncio
import atexit
import configparser

from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_config = configparser.ConfigParser()
_config.read(os.path.join(BASE_DIR, "config.ini"))

ST_URL = _config.get("headless", "st_url", fallback="http://127.0.0.1:8000")
HEADLESS_MODE = _config.getboolean("headless", "headless", fallback=True)
VIEWPORT_WIDTH = _config.getint("headless", "viewport_width", fallback=600)
REFRESH_DELAY = _config.getint("timing", "refresh_delay", fallback=5)
CHAT_SWITCH_DELAY = _config.getint("timing", "chat_switch_delay", fallback=3)
RENDER_OUTPUT_DIR = os.path.join(BASE_DIR, "rendered")

_playwright = None
_browser = None
_page = None

_processing_lock = False
_processing_relay_id = None


def acquire_lock(relay_id):
    global _processing_lock, _processing_relay_id
    if _processing_lock:
        return False
    _processing_lock = True
    _processing_relay_id = relay_id
    return True


def release_lock():
    global _processing_lock, _processing_relay_id
    _processing_lock = False
    _processing_relay_id = None


def is_locked():
    return _processing_lock


async def init_browser():
    global _playwright, _browser, _page
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=HEADLESS_MODE)
    context = await _browser.new_context(
        viewport={"width": VIEWPORT_WIDTH + 80, "height": 800}
    )
    _page = await context.new_page()
    await _page.goto(ST_URL, wait_until="domcontentloaded")
    await _page.wait_for_function(
        "() => window.SillyTavern && window.SillyTavern.getContext",
        timeout=30000,
    )
    print(f"[headless] 浏览器已启动, ST已就绪, viewport={VIEWPORT_WIDTH + 80}x800")


async def close_browser():
    global _browser, _playwright, _page
    if _page:
        try:
            await _page.close()
        except Exception:
            pass
        _page = None
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    print("[headless] 浏览器已关闭")


def _cleanup():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(close_browser())
        else:
            loop.run_until_complete(close_browser())
    except Exception:
        pass


atexit.register(_cleanup)


async def dismiss_toasts():
    """清除ST页面上所有toastr通知，避免遮挡截图内容"""
    try:
        await _page.evaluate("() => { if (typeof toastr !== 'undefined') toastr.clear(); }")
    except Exception:
        pass


async def inject_message(text: str, relay_id: str) -> bool:
    """向ST注入消息并点击发送"""
    clean = re.sub(r'^/st\s*', '', text)
    try:
        await _page.fill("#send_textarea", clean)
        await _page.evaluate(
            """(text) => {
                const el = document.getElementById('send_textarea');
                el.value = text;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
            clean,
        )
        await _page.click("#send_but")
        print(f"[headless] 消息已注入, relay_id={relay_id}: {clean[:50]}...", flush=True)
        return True
    except Exception as e:
        print(f"[headless] 消息注入失败: {e}", flush=True)
        return False


async def wait_for_response(relay_id: str, timeout: float = 120.0) -> dict | None:
    """监控#mes_stop→#send_but按钮切换来判断LLM生成完成，返回 {content, reasoning}"""
    timeout_ms = int(timeout * 1000)

    try:
        # 等待生成开始（停止按钮可见）
        await _page.wait_for_selector("#mes_stop", state="visible", timeout=10000)
        print(f"[headless] 检测到生成开始 (stop按钮可见), relay_id={relay_id}", flush=True)
    except Exception:
        # 可能瞬间就生成完了，或者按钮状态异常
        print(f"[headless] 未检测到stop按钮, relay_id={relay_id}", flush=True)

    try:
        # 等待生成结束（发送按钮重新可见）
        await _page.wait_for_selector("#send_but", state="visible", timeout=timeout_ms)
        print(f"[headless] 检测到生成完成 (send按钮可见), relay_id={relay_id}", flush=True)
    except Exception:
        print(f"[headless] 等待send按钮超时, relay_id={relay_id}", flush=True)
        return None

    # 读取最后一条assistant消息
    result = await _page.evaluate(
        """() => {
            const st = window.SillyTavern;
            if (!st) return null;
            const ctx = st.getContext();
            if (!ctx || !ctx.chat) return null;
            for (let i = ctx.chat.length - 1; i >= 0; i--) {
                const msg = ctx.chat[i];
                if (msg && !msg.is_user && !msg.is_system && msg.mes) {
                    return {
                        content: msg.mes,
                        reasoning: (msg.extra && (msg.extra.reasoning || msg.extra.reasoning_content)) || "",
                    };
                }
            }
            return null;
        }"""
    )

    if result:
        print(
            f"[headless] 回复已捕获, relay_id={relay_id}, "
            f"len={len(result['content'])}, reasoning_len={len(result.get('reasoning', ''))}",
            flush=True
        )
    return result


async def swipe_left() -> bool:
    """切换到上一个备选回复（左翻页）"""
    try:
        btn = _page.locator(".mes.last_mes .swipe_left")
        await btn.wait_for(state="visible", timeout=3000)
        await btn.click()
        await _page.wait_for_timeout(300)
        await dismiss_toasts()
        print("[headless] 已向左翻页")
        return True
    except Exception as e:
        print(f"[headless] 左翻页失败: {e}")
        return False


async def swipe_right() -> str | None:
    """切换到下一个备选回复（右翻页），若在最后一条则可能触发新生成
    返回 'swiped' 表示已切换，'generating' 表示触发了LLM生成，None 表示失败"""
    try:
        btn = _page.locator(".mes.last_mes .swipe_right")
        await btn.wait_for(state="visible", timeout=3000)
        await btn.click()

        # 检测是否触发了新生成
        try:
            await _page.wait_for_selector("#mes_stop", state="visible", timeout=2000)
            print("[headless] 右翻页触发了新生成")
            return "generating"
        except Exception:
            await _page.wait_for_timeout(300)
            await dismiss_toasts()
            print("[headless] 已向右翻页")
            return "swiped"
    except Exception as e:
        print(f"[headless] 右翻页失败: {e}")
        return None


async def regenerate() -> bool:
    """通过ST JS API触发重新生成"""
    try:
        await _page.evaluate(
            "() => window.SillyTavern.getContext().generate('regenerate')"
        )
        print("[headless] 已触发重新生成", flush=True)
        return True
    except Exception as e:
        print(f"[headless] 重新生成失败: {e}")
        return False


async def capture_screenshot(output_dir: str = None) -> str | None:
    """截取最后一条消息容器的截图，包含插件渲染内容，支持溢出内容完整截取"""
    if output_dir is None:
        output_dir = RENDER_OUTPUT_DIR

    os.makedirs(output_dir, exist_ok=True)
    filename = "nc_msg.png"
    output_path = os.path.join(output_dir, filename)

    await dismiss_toasts()

    try:
        # 优先截取完整消息容器(.mes)，比.mes_text包含更多渲染内容
        el = _page.locator(".mes").last
        await el.wait_for(state="visible", timeout=5000)
        
        # 获取元素 bounding box 并调整视口以完整显示
        box = await el.bounding_box()
        if box:
            # 获取当前页面视口
            viewport = _page.viewport_size
            original_height = viewport["height"]
            original_width = viewport["width"]
            
            # 计算需要的高度（元素高度 + 额外空间）
            needed_height = int(box["height"] + 200)
            if needed_height > original_height:
                try:
                    # 临时调整视口以容纳完整内容
                    await _page.set_viewport_size({"width": original_width, "height": needed_height})
                    await _page.wait_for_timeout(300)
                except Exception:
                    pass
            
            try:
                # 滚动到元素顶部
                await el.scroll_into_view_if_needed()
                await _page.wait_for_timeout(200)
            except Exception:
                pass
            
            # 使用元素截图并启用 full_page 模式
            await el.screenshot(path=output_path, type="png")
            print(f"[headless] 消息容器截图已保存: {output_path} (元素高度: {box['height']})")
            
            # 恢复原视口大小
            try:
                await _page.set_viewport_size({"width": original_width, "height": original_height})
            except Exception:
                pass
            
            return output_path
        else:
            # 无法获取 bounding box，使用普通截图
            await el.screenshot(path=output_path, type="png")
            print(f"[headless] 消息容器截图已保存: {output_path}")
            return output_path
            
    except Exception as e:
        print(f"[headless] 消息容器截图失败({e})，尝试.mes_text")
        try:
            el = _page.locator(".mes_text").last
            await el.wait_for(state="visible", timeout=5000)
            
            # 同样处理 .mes_text 元素
            box = await el.bounding_box()
            if box:
                viewport = _page.viewport_size
                original_height = viewport["height"]
                original_width = viewport["width"]
                needed_height = int(box["height"] + 200)
                if needed_height > original_height:
                    await _page.set_viewport_size({"width": original_width, "height": needed_height})
                    await _page.wait_for_timeout(300)
                await el.scroll_into_view_if_needed()
                await _page.wait_for_timeout(200)
            
            await el.screenshot(path=output_path, type="png")
            print(f"[headless] 消息文本截图已保存: {output_path}")
            
            # 恢复视口
            try:
                viewport = _page.viewport_size
                await _page.set_viewport_size({"width": viewport["width"], "height": 800})
            except Exception:
                pass
            
            return output_path
        except Exception as e2:
            print(f"[headless] 元素截图均失败({e2})，回退全页截图")
        try:
            await _page.screenshot(path=output_path, full_page=True)
            print(f"[headless] 全页截图已保存: {output_path}")
            return output_path
        except Exception as e2:
            print(f"[headless] 截图完全失败: {e2}")
            return None


async def capture_full_screenshot(output_dir: str = None) -> str | None:
    """截取整个ST页面的完整截图"""
    if output_dir is None:
        output_dir = RENDER_OUTPUT_DIR

    os.makedirs(output_dir, exist_ok=True)
    filename = "nc_full.png"
    output_path = os.path.join(output_dir, filename)

    await dismiss_toasts()

    try:
        await _page.screenshot(path=output_path, full_page=True)
        print(f"[headless] 全页截图已保存: {output_path}")
        return output_path
    except Exception as e:
        print(f"[headless] 全页截图失败: {e}")
        return None


async def refresh_page() -> bool:
    """刷新ST页面并等待就绪"""
    try:
        await _page.reload(wait_until="domcontentloaded")
        await _page.wait_for_function(
            "() => window.SillyTavern && window.SillyTavern.getContext",
            timeout=30000,
        )
        await _page.wait_for_timeout(REFRESH_DELAY * 1000)  # 等待页面渲染完成
        print("[headless] 页面已刷新, ST已就绪")
        return True
    except Exception as e:
        print(f"[headless] 页面刷新失败: {e}")
        return False


async def open_chat(file_name: str) -> bool:
    """通过JS API打开指定聊天文件(先选角色再打开聊天)"""
    try:
        # ST内部自动加.jsonl后缀，所以要去掉
        clean_file = file_name.replace(".jsonl", "")

        await _page.evaluate(
            """async (file_name) => {
                const ctx = window.SillyTavern.getContext();

                // 确保角色卡列表已加载
                await ctx.getCharacters();

                // 从文件名提取角色名: "CharName - timestamp"
                const cleanName = file_name.replace('.jsonl', '');
                const dashIdx = cleanName.lastIndexOf(' - ');
                let chId = -1;

                if (dashIdx > 0) {
                    const charName = cleanName.substring(0, dashIdx);
                    // 先尝试精确chat匹配（ST内部存储无.jsonl后缀）
                    for (let i = 0; i < ctx.characters.length; i++) {
                        if (ctx.characters[i] && ctx.characters[i].chat === cleanName) {
                            chId = i;
                            break;
                        }
                    }
                    // 再尝试角色名匹配
                    if (chId === -1) {
                        for (let i = 0; i < ctx.characters.length; i++) {
                            if (ctx.characters[i] && ctx.characters[i].name === charName) {
                                chId = i;
                                break;
                            }
                        }
                    }
                }

                if (chId === -1) {
                    throw new Error('找不到对应角色: ' + file_name);
                }

                // 先选定角色（设置this_chid），再打开聊天
                await ctx.selectCharacterById(chId, {switchMenu: true});
                // openCharacterChat内部自动追加.jsonl，传无后缀名
                await ctx.openCharacterChat(cleanName);
                return true;
            }""",
            clean_file,
        )
        await _page.wait_for_timeout(CHAT_SWITCH_DELAY * 1000)
        await dismiss_toasts()
        print(f"[headless] 已打开聊天: {file_name}")
        return True
    except Exception as e:
        print(f"[headless] 打开聊天失败: {e}")
        return False


async def fetch_recent_chats() -> list:
    """从浏览器上下文获取最近聊天列表"""
    try:
        data = await _page.evaluate(
            """async () => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const resp = await fetch('/api/chats/recent', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({}),
                });
                if (!resp.ok) return [];
                return await resp.json();
            }"""
        )
        print(f"[headless] 获取到 {len(data)} 条最近聊天")
        return data
    except Exception as e:
        print(f"[headless] 获取最近聊天失败: {e}")
        return []


async def fetch_characters() -> list:
    """从浏览器上下文获取角色卡列表"""
    try:
        data = await _page.evaluate(
            """async () => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const resp = await fetch('/api/characters/all', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({}),
                });
                if (!resp.ok) return [];
                return await resp.json();
            }"""
        )
        print(f"[headless] 获取到 {len(data)} 个角色卡")
        return data
    except Exception as e:
        print(f"[headless] 获取角色卡列表失败: {e}")
        return []


async def fetch_character_chats(avatar_url: str) -> list:
    """从浏览器上下文获取指定角色的所有聊天记录"""
    try:
        data = await _page.evaluate(
            """async (avatar_url) => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const resp = await fetch('/api/characters/chats', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({avatar_url: avatar_url}),
                });
                if (!resp.ok) return [];
                return await resp.json();
            }""",
            avatar_url,
        )
        print(f"[headless] 获取到角色({avatar_url})的 {len(data)} 条聊天记录")
        return data
    except Exception as e:
        print(f"[headless] 获取角色聊天记录失败: {e}")
        return []


async def delete_messages(n: int = 1) -> bool:
    """通过STscript删除当前聊天最后N条消息(仅支持1或2)"""
    if n not in (1, 2):
        n = 1
    try:
        await _page.evaluate(
            """async (n) => {
                const ctx = window.SillyTavern.getContext();
                await ctx.executeSlashCommands(`/del ${n}`);
            }""",
            n,
        )
        await _page.wait_for_timeout(500)
        print(f"[headless] 已删除最后 {n} 条消息")
        return True
    except Exception as e:
        print(f"[headless] 删除消息失败: {e}")
        return False


async def delete_chat(file_name: str) -> bool:
    """通过API删除指定聊天文件"""
    try:
        clean_file = file_name.replace(".jsonl", "")
        await _page.evaluate(
            """async (file_name) => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();

                // 从文件名提取角色名
                const dashIdx = file_name.lastIndexOf(' - ');
                if (dashIdx < 0) throw new Error('Invalid file name');
                const charName = file_name.substring(0, dashIdx);

                // 查找角色avatar
                let avatar = '';
                for (let i = 0; i < ctx.characters.length; i++) {
                    if (ctx.characters[i] && ctx.characters[i].name === charName) {
                        avatar = ctx.characters[i].avatar;
                        break;
                    }
                }

                // 调用删除API
                const resp = await fetch('/api/chats/delete', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({
                        ch_name: charName,
                        file_name: file_name,
                        avatar_url: avatar,
                    }),
                });
                if (!resp.ok) throw new Error('Delete failed: ' + resp.status);
                return true;
            }""",
            clean_file,
        )
        await _page.wait_for_timeout(500)
        print(f"[headless] 已删除聊天: {clean_file}")
        return True
    except Exception as e:
        print(f"[headless] 删除聊天失败: {e}")
        return False


async def cancel_processing():
    """点击ST的停止按钮"""
    global _processing_lock, _processing_relay_id
    try:
        await _page.click("#mes_stop")
        print(f"[headless] 已点击停止按钮, relay_id={_processing_relay_id}")
    except Exception as e:
        print(f"[headless] 停止按钮失败: {e}")
    relay_id = _processing_relay_id
    release_lock()
    return relay_id

