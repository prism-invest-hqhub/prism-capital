# 🔷 棱镜 Prism Capital

独立投资数据终端 — 实时行情 · 可转债筛选 · JWT鉴权

## 一键部署

```bash
git clone https://github.com/YOUR_USERNAME/prism-capital.git
cd prism-capital
bash deploy.sh
```

## 功能

| 端点 | 说明 |
|------|------|
| `GET /` | 服务信息 |
| `GET /health` | 健康检查 |
| `POST /token` | 签发JWT Token |
| `GET /realtime?codes=sh600519` | 实时行情 |
| `GET /index` | 核心指数 |
| `GET /bond/double-low?top=30` | 可转债双低排名 |
| `GET /app` | PWA界面 |

## 签发Token

```bash
curl -X POST http://localhost:8900/token \
  -H "Content-Type: application/json" \
  -d '{"admin_key":"prism-admin-2026","subject":"user-name","role":"admin","expiry_days":365}'
```

## 数据源

- 腾讯财经（主力）+ 新浪（备用）
- efinance（可转债基础列表）
- 可转债双低 = efinance列表 + 腾讯批量行情 + 本地评级过滤

## 定价

- 内部使用：免费
- 外部调用：$19/月
