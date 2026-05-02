import os
import re
import uuid
import html as _html_mod
import atexit
import markdown
from playwright.async_api import async_playwright

_browser = None
_playwright = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = os.path.join(BASE_DIR, "pages")


def _save_page(html: str, image_filename: str) -> None:
    """保存渲染后的完整HTML页面到pages目录，便于排查渲染问题"""
    os.makedirs(PAGES_DIR, exist_ok=True)
    base = os.path.splitext(image_filename)[0]
    page_path = os.path.join(PAGES_DIR, f"{base}.html")
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[render] 页面已保存: {page_path}")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    width: {width}px;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
    font-size: 16px;
    line-height: 1.75;
    color: #e0e0e0;
    background: #2b2b2b;
    padding: 24px 20px;
    word-break: break-word;
}}
h1 {{ font-size: 1.5em; margin: 16px 0 8px; border-bottom: 2px solid #4A90D9; padding-bottom: 4px; }}
h2 {{ font-size: 1.3em; margin: 14px 0 6px; }}
h3 {{ font-size: 1.15em; margin: 12px 0 4px; }}
h4, h5, h6 {{ font-size: 1.05em; margin: 10px 0 4px; }}
p {{ margin: 6px 0; }}
ul, ol {{ padding-left: 24px; margin: 6px 0; }}
li {{ margin: 2px 0; }}
blockquote {{
    border-left: 4px solid #4A90D9;
    padding: 4px 12px;
    margin: 8px 0;
    background: #1e1e1e;
    color: #aaa;
}}
code {{
    background: #1e1e1e;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 0.9em;
}}
pre {{
    background: #2d2d2d;
    color: #f8f8f2;
    padding: 14px 16px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 8px 0;
    font-size: 0.88em;
    line-height: 1.5;
}}
pre code {{ background: none; padding: 0; color: inherit; }}
table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
th, td {{ border: 1px solid #444; padding: 8px 10px; text-align: left; }}
th {{ background: #1e1e1e; font-weight: 600; }}
hr {{ border: none; border-top: 1px solid #444; margin: 12px 0; }}
a {{ color: #6db3f2; }}
strong {{ font-weight: 600; }}
.rendered-html {{
    margin: 8px 0;
    padding: 0;
}}
.rendered-html > * {{ margin: 4px 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""

REASONING_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    width: {width}px;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
    font-size: 14px;
    line-height: 1.7;
    color: #666;
    background: #fafaf5;
    padding: 20px 18px;
    word-break: break-word;
}}
.thinking-label {{
    display: inline-block;
    background: #e8e0d0;
    color: #8b7355;
    font-size: 12px;
    padding: 2px 10px;
    border-radius: 10px;
    margin-bottom: 10px;
}}
</style>
</head>
<body>
<div class="thinking-label">思考过程</div>
<div>{body}</div>
</body>
</html>"""


def strip_code_blocks(text: str) -> str:
    return re.sub(r'```[^\n]*\n.*?```', '', text, flags=re.DOTALL).strip()


def _clean_message(text: str) -> str:
    """清洗CQ码和XML标签残留"""
    text = re.sub(r'\[CQ:[^\]]*\]', '', text)
    text = re.sub(r'<\?xml[^?]*\?>', '', text)
    text = re.sub(r'<UpdateVariable>.*?</UpdateVariable>', '', text, flags=re.DOTALL)
    text = re.sub(r'<JSONPatch>.*?</JSONPatch>', '', text, flags=re.DOTALL)
    # 移除ST插件的"显示前端代码块"折叠按钮
    text = re.sub(r'<div[^>]*TH-collapse-code-block-button[^>]*>[^<]*</div>', '', text)
    return text.strip()


def _sanitize_html_block(html_block: str) -> str:
    """处理完整HTML文档：剥离<html>/<head>/<body>外层标签，保留style和body内容"""
    has_doctype = bool(re.search(r'<!DOCTYPE\s+html', html_block, re.IGNORECASE))
    has_html_tag = bool(re.search(r'<html[\s>]', html_block, re.IGNORECASE))

    if not has_doctype and not has_html_tag:
        return html_block

    styles = re.findall(r'<style[^>]*>(.*?)</style>', html_block, re.DOTALL | re.IGNORECASE)

    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_block, re.DOTALL | re.IGNORECASE)
    if body_match:
        inner = body_match.group(1).strip()
    else:
        inner = html_block
        for tag in ['<!DOCTYPE[^>]*>', '</?html[^>]*>', '</?head[^>]*>',
                     '</?body[^>]*>', '<meta[^>]*>', '<title[^>]*>.*?</title>']:
            inner = re.sub(tag, '', inner, flags=re.DOTALL | re.IGNORECASE)
        inner = inner.strip()

    inner = re.sub(r'<script[^>]*>.*?</script>', '', inner, flags=re.DOTALL | re.IGNORECASE)
    inner = re.sub(r'<link[^>]*>', '', inner, flags=re.IGNORECASE)

    if styles:
        # 过滤掉会污染外层模板的body/html/*规则
        scoped_styles = []
        for s in styles:
            s = re.sub(r'body\s*\{[^}]*\}', '', s)
            s = re.sub(r'html\s*\{[^}]*\}', '', s)
            s = re.sub(r'\*\s*\{[^}]*\}', '', s)
            if s.strip():
                scoped_styles.append(s)
        if scoped_styles:
            style_block = '<style>\n' + '\n'.join(scoped_styles) + '\n</style>'
            inner = style_block + '\n' + inner

    return inner


def _unwrap_html_code_blocks(html_content: str) -> str:
    """将ST渲染后的语法高亮HTML代码块还原为可渲染的HTML组件"""
    def _extract(m):
        inner = m.group(1)
        # 剥离highlight.js的语法高亮span标签
        inner = re.sub(r'<span[^>]*>', '', inner)
        inner = inner.replace('</span>', '')
        # 剥离其他可能嵌套的标签（如code内的b/i等）
        inner = re.sub(r'</?(?:b|i|em|strong|u|mark)[^>]*>', '', inner)
        # 解码HTML实体
        inner = _html_mod.unescape(inner)
        inner = _sanitize_html_block(inner)
        return f'<div class="rendered-html">{inner}</div>'

    # 匹配 <code class="...custom-html...">...</code>
    return re.sub(
        r'<code[^>]*custom-html[^>]*>(.*?)</code>',
        _extract,
        html_content,
        flags=re.DOTALL
    )


def _strip_encoded_html(text: str) -> str:
    """移除实体编码的HTML文档片段（插件iframe srcdoc残留的编码源码）"""
    # 匹配 &lt;body&gt;...&lt;/body&gt; 编码块
    text = re.sub(r'&lt;body&gt;.*?&lt;/body&gt;', '', text, flags=re.DOTALL)
    # 清理残留的编码文档级标签
    for tag in ['&lt;!DOCTYPE[^&]*&gt;', '&lt;html[^&]*&gt;', '&lt;/html&gt;',
                '&lt;head&gt;', '&lt;/head&gt;', '&lt;/script&gt;']:
        text = re.sub(r'\s*' + tag, '', text, flags=re.DOTALL)
    # 清理因移除上述内容产生的连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _markdown_to_html(text: str) -> str:
    html_blocks = []

    def _extract(m):
        html_blocks.append(_sanitize_html_block(m.group(1)))
        return f"<!--HTML_BLOCK_{len(html_blocks) - 1}-->"

    processed = re.sub(
        r'```html\s*\n(.*?)```', _extract, text, flags=re.DOTALL
    )

    md = markdown.Markdown(extensions=['fenced_code', 'tables', 'codehilite', 'nl2br'])
    html = md.convert(processed)

    for i, block in enumerate(html_blocks):
        html = html.replace(
            f'<!--HTML_BLOCK_{i}-->',
            f'<div class="rendered-html">{block}</div>'
        )

    return html


async def _get_browser():
    global _browser, _playwright
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
    return _browser


def _cleanup():
    global _browser, _playwright
    try:
        import asyncio
        if _browser:
            asyncio.get_event_loop().run_until_complete(_browser.close())
        if _playwright:
            asyncio.get_event_loop().run_until_complete(_playwright.stop())
    except Exception:
        pass


atexit.register(_cleanup)


async def render_to_image(markdown_text: str, output_dir: str, width: int = 600) -> str | None:
    if not markdown_text or not markdown_text.strip():
        return None

    os.makedirs(output_dir, exist_ok=True)

    cleaned = _clean_message(markdown_text)
    html_body = _markdown_to_html(cleaned)
    html = HTML_TEMPLATE.format(width=width, body=html_body)

    filename = f"nc_{uuid.uuid4().hex[:10]}.png"
    output_path = os.path.join(output_dir, filename)

    tmp_html = os.path.join(output_dir, f"_tmp_{uuid.uuid4().hex[:6]}.html")
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        browser = await _get_browser()
        page = await browser.new_page(viewport={"width": width + 40, "height": 600})
        await page.goto(f"file:///{tmp_html.replace(os.sep, '/')}", wait_until="networkidle")
        await page.screenshot(path=output_path, full_page=True)
        await page.close()
        _save_page(html, filename)
        print(f"[render] 图片已保存: {output_path}")
        return output_path
    except Exception as e:
        print(f"[render] 渲染失败: {e}")
        return None
    finally:
        try:
            os.remove(tmp_html)
        except OSError:
            pass


async def render_reasoning_to_image(reasoning_text: str, output_dir: str, width: int = 600) -> str | None:
    if not reasoning_text or not reasoning_text.strip():
        return None

    os.makedirs(output_dir, exist_ok=True)

    escaped = (
        reasoning_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
    html = REASONING_TEMPLATE.format(width=width, body=escaped)

    filename = f"nc_reasoning_{uuid.uuid4().hex[:10]}.png"
    output_path = os.path.join(output_dir, filename)

    tmp_html = os.path.join(output_dir, f"_tmp_{uuid.uuid4().hex[:6]}.html")
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        browser = await _get_browser()
        page = await browser.new_page(viewport={"width": width + 40, "height": 400})
        await page.goto(f"file:///{tmp_html.replace(os.sep, '/')}", wait_until="networkidle")
        await page.screenshot(path=output_path, full_page=True)
        await page.close()
        _save_page(html, filename)
        print(f"[render] 思维链图片已保存: {output_path}")
        return output_path
    except Exception as e:
        print(f"[render] 思维链渲染失败: {e}")
        return None
    finally:
        try:
            os.remove(tmp_html)
        except OSError:
            pass


async def render_html_to_image(html_content: str, output_dir: str, width: int = 600) -> str | None:
    """直接渲染已生成的HTML内容（跳过markdown转换），用于ST插件捕获的渲染后DOM"""
    if not html_content or not html_content.strip():
        return None

    os.makedirs(output_dir, exist_ok=True)

    html_content = _clean_message(html_content)
    html_content = _unwrap_html_code_blocks(html_content)
    html_content = _strip_encoded_html(html_content)
    html_content = _sanitize_html_block(html_content)
    html = HTML_TEMPLATE.format(width=width, body=f'<div class="rendered-html">{html_content}</div>')

    filename = f"nc_{uuid.uuid4().hex[:10]}.png"
    output_path = os.path.join(output_dir, filename)

    tmp_html = os.path.join(output_dir, f"_tmp_{uuid.uuid4().hex[:6]}.html")
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        browser = await _get_browser()
        page = await browser.new_page(viewport={"width": width + 40, "height": 600})
        await page.goto(f"file:///{tmp_html.replace(os.sep, '/')}", wait_until="networkidle")
        await page.screenshot(path=output_path, full_page=True)
        await page.close()
        _save_page(html, filename)
        print(f"[render] HTML图片已保存: {output_path}")
        return output_path
    except Exception as e:
        print(f"[render] HTML渲染失败: {e}")
        return None
    finally:
        try:
            os.remove(tmp_html)
        except OSError:
            pass
