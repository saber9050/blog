"""浏览器落地页。

只用于「用户点邮件链接」这类场景：他在浏览器里直接打开一个 URL，
不该看到 JSON，而应该看到一张提示卡片。

四种结果（成功 / 缺参数 / token 无效 / token 已用）**全部返回 HTTP 200**，
成败只体现在页面内容上 —— 这是 Go 版的既有行为，改状态码会让
邮件客户端或浏览器插件把页面当成错误页，反而看不到提示。
"""

from html import escape

from fastapi.responses import HTMLResponse

# 内联样式：不依赖外部 CSS，也不依赖前端 SPA。
# 邮件里的链接可能被各种浏览器/客户端打开，能自带样式就自带。
_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 个人博客</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    background: #f5f7fa; min-height: 100vh;
    display: flex; align-items: center; justify-content: center; padding: 20px;
  }}
  .card {{
    max-width: 480px; width: 100%; background: #fff; border-radius: 20px;
    box-shadow: 0 10px 25px -5px rgba(0,0,0,.08), 0 8px 10px -6px rgba(0,0,0,.02);
    text-align: center; padding: 40px 32px;
  }}
  .icon {{ font-size: 64px; line-height: 1; margin-bottom: 24px; }}
  .icon.ok {{ color: #10b981; }}
  .icon.fail {{ color: #ef4444; }}
  h2 {{ font-size: 26px; font-weight: 600; margin-bottom: 16px; color: #1f2937; }}
  p {{ font-size: 16px; color: #4b5563; line-height: 1.6; word-break: break-word; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon {icon_class}">{icon}</div>
    <h2>{title}</h2>
    <p>{message}</p>
  </div>
</body>
</html>"""


def render_result_page(title: str, message: str, *, success: bool) -> HTMLResponse:
    """渲染结果提示页。

    Args:
        title: 页面标题，如「邮箱修改成功」。
        message: 正文说明。
        success: 决定图标与颜色（绿勾 / 红叉）。

    Returns:
        固定 HTTP 200 的 HTMLResponse。

    说明：`title` 与 `message` 都是服务端写死的文案，不是用户输入，
    但仍然做一次 HTML 转义 —— 万一将来有人把用户可控内容传进来。
    """
    html = _TEMPLATE.format(
        title=escape(title),
        message=escape(message),
        success=success,
        icon_class="ok" if success else "fail",
        icon="&#10004;" if success else "&#10008;",
    )
    return HTMLResponse(content=html, status_code=200)
