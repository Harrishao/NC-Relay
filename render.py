import os
import re
import uuid
import atexit
import markdown
from playwright.async_api import async_playwright

_browser = None
_playwright = None

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
    color: #222;
    background: #fff;
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
    background: #f0f4f8;
    color: #555;
}}
code {{
    background: #f4f4f4;
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
th, td {{ border: 1px solid #ddd; padding: 8px 10px; text-align: left; }}
th {{ background: #f0f4f8; font-weight: 600; }}
hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 12px 0; }}
a {{ color: #4A90D9; }}
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


def _markdown_to_html(text: str) -> str:
    html_blocks = []

    def _extract(m):
        html_blocks.append(m.group(1))
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

    html_body = _markdown_to_html(markdown_text)
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
