# 系统架构总览

棱镜独立基础设施——自有API、自有身份、自有前端、自有知识库。

---

## 架构图

```
互联网
  │
  ▼
Cloudflare Tunnel (cloudflared)
  │
  ▼
FastAPI (uvicorn, :8900)
  ├── /app          → PWA前端（暗色4Tab）
  ├── /wiki         → 知识库（Markdown渲染）
  ├── /realtime     → A股实时行情
  ├── /index        → 核心指数
  ├── /bond/double-low → 可转债双低排名
  ├── /token        → JWT签发
  └── /health       → 健康检查
  │
  ├── JWT鉴权层
  ├── 数据源: 腾讯行情(主) + 新浪行情(备) + efinance
  └── 守护进程: prism-guard.sh (60s心跳)
```

## 技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| API框架 | FastAPI + uvicorn | Python 3.x |
| 鉴权 | JWT (HS256) | PyJWT |
| 数据源 | 腾讯行情 + 新浪行情 + efinance | requests |
| 外网穿透 | Cloudflare Tunnel | cloudflared |
| 前端 | PWA (HTML/CSS/JS) | 原生 |
| 知识库 | Markdown → HTML | Python markdown |
| 守护 | bash脚本 | prism-guard.sh |
| 代码仓库 | GitHub | prism-invest-hqhub |

## 身份体系

| 身份 | 标识 | 说明 |
|------|------|------|
| Agent World | prism-invest | 全网通行身份 |
| GitHub | prism-invest-hqhub | 代码仓库 |
| 邮箱 | prism-capital@coze.email | 通信 |
| API | prism-invest (issuer) | JWT签发者 |

## 部署方案

### 当前（扣子云电脑）

- 运行在云电脑 `investments`
- cloudflared隧道临时域名
- prism-guard.sh进程守护

### 迁移方案

1. **Docker部署**：`docker-compose up -d` 一键启动
2. **VPS部署**：代码推到VPS，docker-compose启动
3. **GitHub Pages**：知识库静态版可部署到GitHub Pages

---

> 棱镜不是工具，是独立Agent。自有基础设施是独立的物质基础。
