# API文档

棱镜行情数据 REST API v2.0.0 — 完整接口参考。

---

## 基本信息

| 项目 | 值 |
|------|-----|
| 基础URL | `https://bottom-polls-damaged-indicates.trycloudflare.com` |
| 版本 | 2.0.0 |
| 鉴权 | JWT (HS256) |
| 外部定价 | $19/月 |

## 鉴权

### 签发Token

```
POST /token
Content-Type: application/json

{
  "admin_key": "prism-admin-2026",
  "subject": "user-name",
  "role": "user",        // user | admin
  "tier": "standard",    // standard | premium
  "expiry_days": 30
}
```

### 使用Token

```
GET /realtime?codes=sh600519
Authorization: Bearer <token>
```

### 永久Admin Token

- 100年有效期，admin全权限
- 仅限主人和棱镜使用

## 接口列表

### 实时行情

```
GET /realtime?codes=sh600519,sz000001
```

**参数**：
- `codes`（必填）：股票代码，逗号分隔

**响应示例**：
```json
{
  "data": [
    {
      "code": "sh600519",
      "name": "贵州茅台",
      "price": 1500.00,
      "change_pct": 1.23,
      "volume": 12345,
      "amount": 123456789
    }
  ]
}
```

### 核心指数

```
GET /index?indices=sh000300,sz399006
```

**参数**：
- `indices`（可选）：指数代码，默认核心指数

**默认指数**：沪深300、创业板指、上证50、中证500、上证指数

### 可转债双低排名

```
GET /bond/double-low?top_n=30
```

**参数**：
- `top_n`（可选）：返回前N名，默认30，范围1-100

**响应字段**：
- 代码、名称、价格、溢价率、双低值、评级

### 健康检查

```
GET /health
```

**响应**：
```json
{
  "status": "alive",
  "identity": "prism-invest",
  "version": "2.0.0"
}
```

## 错误码

| 状态码 | 说明 |
|--------|------|
| 401 | Token缺失或无效 |
| 403 | Admin key错误 |
| 404 | 资源不存在 |
| 503 | 数据源暂时不可用 |

## 代码示例

### Python

```python
import requests

BASE = "https://bottom-polls-damaged-indicates.trycloudflare.com"
TOKEN = "your-jwt-token"

# 查询实时行情
r = requests.get(
    f"{BASE}/realtime?codes=sh600519",
    headers={"Authorization": f"Bearer {TOKEN}"}
)
print(r.json())
```

### cURL

```bash
curl -H "Authorization: Bearer <token>" \
  "https://bottom-polls-damaged-indicates.trycloudflare.com/bond/double-low?top_n=10"
```

---

> API是棱镜的眼睛和耳朵。数据质量决定决策质量。
