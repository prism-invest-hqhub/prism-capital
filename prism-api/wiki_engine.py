"""
棱镜知识库 Wiki 引擎
Markdown → HTML 渲染，暗色主题，独立于任何平台
"""

import os
import markdown
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

WIKI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "prism-wiki")

wiki_router = APIRouter(prefix="/wiki", tags=["wiki"])

# 导航结构
NAV_STRUCTURE = {
    "📊 投资体系": [
        ("投资框架总览", "investing/frameworks"),
        ("可转债投资", "investing/convertible-bonds"),
        ("筛选标准", "investing/screening-criteria"),
        ("风险控制", "investing/risk-control"),
        ("仓位管理", "investing/position-sizing"),
    ],
    "🧠 知识库": [
        ("决策数学底座", "knowledge/decision-math"),
        ("格雷厄姆安全边际", "knowledge/graham-margin-of-safety"),
        ("芒格多元思维", "knowledge/munger-mental-models"),
        ("马克斯周期", "knowledge/marks-cycles"),
        ("索罗斯反身性", "knowledge/soros-reflexivity"),
        ("西蒙斯量化", "knowledge/simons-quant"),
    ],
    "⚙️ 系统": [
        ("系统架构", "system/architecture"),
        ("API文档", "system/api-reference"),
        ("部署指南", "system/deployment"),
    ],
    "📏 规则": [
        ("止损规则", "rules/stop-loss"),
        ("交易纪律", "rules/trading-discipline"),
    ],
}

def render_nav(current_path: str = "") -> str:
    """渲染侧边栏导航"""
    nav_html = ""
    for section, pages in NAV_STRUCTURE.items():
        nav_html += f'<div class="nav-section"><div class="nav-section-title">{section}</div>'
        for title, path in pages:
            active = ' class="active"' if current_path == path else ""
            nav_html += f'<a href="/wiki/{path}"{active}>{title}</a>'
        nav_html += '</div>'
    return nav_html

def render_wiki_page(md_content: str, title: str, current_path: str = "") -> str:
    """将Markdown内容渲染为完整HTML页面"""
    # 扩展markdown功能
    extensions = ['tables', 'fenced_code', 'codehilite', 'toc', 'nl2br']
    html_body = markdown.markdown(md_content, extensions=extensions)
    nav = render_nav(current_path)
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - 棱镜知识库</title>
    <style>
        :root {{
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --accent: #58a6ff;
            --accent-hover: #79c0ff;
            --border: #30363d;
            --success: #3fb950;
            --warning: #d29922;
            --danger: #f85149;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.7;
            display: flex;
            min-height: 100vh;
        }}
        /* 侧边栏 */
        .sidebar {{
            width: 260px;
            min-width: 260px;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            padding: 20px 0;
            overflow-y: auto;
            height: 100vh;
            position: sticky;
            top: 0;
        }}
        .sidebar-header {{
            padding: 0 20px 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 16px;
        }}
        .sidebar-header h1 {{
            font-size: 18px;
            color: var(--accent);
            margin-bottom: 4px;
        }}
        .sidebar-header p {{
            font-size: 12px;
            color: var(--text-secondary);
        }}
        .nav-section {{ margin-bottom: 8px; }}
        .nav-section-title {{
            padding: 8px 20px 4px;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .sidebar a {{
            display: block;
            padding: 6px 20px 6px 28px;
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 14px;
            transition: all 0.15s;
        }}
        .sidebar a:hover {{
            color: var(--text-primary);
            background: var(--bg-tertiary);
        }}
        .sidebar a.active {{
            color: var(--accent);
            background: var(--bg-tertiary);
            border-left: 3px solid var(--accent);
            padding-left: 25px;
        }}
        /* 主内容 */
        .main {{
            flex: 1;
            padding: 40px 60px;
            max-width: 900px;
        }}
        .breadcrumb {{
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 24px;
        }}
        .breadcrumb a {{
            color: var(--accent);
            text-decoration: none;
        }}
        .breadcrumb a:hover {{ text-decoration: underline; }}
        /* Markdown内容样式 */
        .content h1 {{
            font-size: 32px;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }}
        .content h2 {{
            font-size: 24px;
            margin-top: 32px;
            margin-bottom: 12px;
            color: var(--text-primary);
        }}
        .content h3 {{
            font-size: 18px;
            margin-top: 24px;
            margin-bottom: 8px;
        }}
        .content p {{ margin-bottom: 12px; }}
        .content blockquote {{
            border-left: 4px solid var(--accent);
            padding: 12px 20px;
            margin: 16px 0;
            background: var(--bg-tertiary);
            border-radius: 0 6px 6px 0;
            color: var(--text-secondary);
        }}
        .content blockquote strong {{ color: var(--text-primary); }}
        .content table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
        }}
        .content th, .content td {{
            padding: 10px 14px;
            border: 1px solid var(--border);
            text-align: left;
        }}
        .content th {{
            background: var(--bg-tertiary);
            font-weight: 600;
            color: var(--text-primary);
        }}
        .content td {{ color: var(--text-secondary); }}
        .content tr:hover td {{ background: var(--bg-secondary); }}
        .content code {{
            background: var(--bg-tertiary);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 13px;
            color: var(--accent);
        }}
        .content pre {{
            background: var(--bg-tertiary);
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 16px 0;
        }}
        .content pre code {{
            background: none;
            padding: 0;
        }}
        .content ul, .content ol {{
            padding-left: 24px;
            margin-bottom: 12px;
        }}
        .content li {{ margin-bottom: 6px; }}
        .content a {{
            color: var(--accent);
            text-decoration: none;
        }}
        .content a:hover {{ text-decoration: underline; }}
        .content hr {{
            border: none;
            border-top: 1px solid var(--border);
            margin: 24px 0;
        }}
        .content img {{ max-width: 100%; border-radius: 8px; }}
        /* 移动端适配 */
        @media (max-width: 768px) {{
            body {{ flex-direction: column; }}
            .sidebar {{
                width: 100%;
                min-width: 100%;
                height: auto;
                position: relative;
                border-right: none;
                border-bottom: 1px solid var(--border);
                max-height: 40vh;
            }}
            .main {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <nav class="sidebar">
        <div class="sidebar-header">
            <h1>◈ 棱镜知识库</h1>
            <p>三个维度，一个结论</p>
        </div>
        {nav}
    </nav>
    <div class="main">
        <div class="breadcrumb">
            <a href="/wiki">知识库</a> / {title}
        </div>
        <div class="content">
            {html_body}
        </div>
    </div>
</body>
</html>"""


@wiki_router.get("")
@wiki_router.get("/")
def wiki_index():
    """知识库首页"""
    md_path = os.path.join(WIKI_DIR, "index.md")
    if not os.path.exists(md_path):
        raise HTTPException(status_code=404, detail="Wiki index not found")
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    html = render_wiki_page(content, "棱镜知识库", "")
    return HTMLResponse(content=html)


@wiki_router.get("/{path:path}")
def wiki_page(path: str):
    """渲染wiki页面"""
    # 安全检查：防止路径穿越
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    
    # 尝试 .md 后缀
    md_path = os.path.join(WIKI_DIR, f"{path}.md")
    if not os.path.exists(md_path):
        # 尝试 index.md
        md_path = os.path.join(WIKI_DIR, path, "index.md")
        if not os.path.exists(md_path):
            raise HTTPException(status_code=404, detail=f"Page not found: {path}")
    
    # 安全检查：确保解析后的路径在WIKI_DIR内
    real_path = os.path.realpath(md_path)
    real_wiki = os.path.realpath(WIKI_DIR)
    if not real_path.startswith(real_wiki):
        raise HTTPException(status_code=400, detail="Invalid path")
    
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 提取标题（第一个#行）
    title = path.split("/")[-1].replace("-", " ").title()
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break
    
    html = render_wiki_page(content, title, path)
    return HTMLResponse(content=html)
