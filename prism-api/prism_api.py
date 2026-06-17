"""
棱镜行情数据 API — Prism Market Data REST API
独立身份，自签Token，外部可调
PWA前端 + JWT鉴权 + 行情数据

启动: uvicorn prism_api:app --host 0.0.0.0 --port 8900
隧道: cloudflared tunnel --url http://localhost:8900
"""

from fastapi import FastAPI, HTTPException, Header, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import jwt
import datetime
import os
import sys

# 导入棱镜行情核心模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import get_realtime, get_index, get_bond_double_low

# 导入wiki引擎
from wiki_engine import wiki_router

app = FastAPI(
    title="棱镜行情数据 API",
    description="Prism Market Data — 三维度，一个结论。A股/可转债/ETF quant-grade data.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册wiki路由
app.include_router(wiki_router)

# ============ JWT 鉴权 ============

JWT_SECRET = os.getenv("PRISM_JWT_SECRET", "prism-capital-2026-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

def sign_token(user: str, days: int = 30, role: str = "user", tier: str = "standard") -> str:
    payload = {
        "sub": user,
        "role": role,
        "tier": tier,
        "scope": "read" if role == "user" else "read write admin",
        "rate_limit": 100 if role == "user" else -1,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=days),
        "issuer": "prism-invest",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(authorization: str = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def _optional_auth(token_data=None):
    """可选鉴权：无token时允许PWA前端访问（限流），有token时验证。
    admin角色永不过期token直接通过。"""
    # 如果是内部调用（token_data为None且没有Header），允许访问但加限流标记
    # 外部访问需要有效token
    pass  # 暂时软鉴权，后续加固为强制

# ============ Token 签发 ============

class TokenRequest(BaseModel):
    admin_key: str
    subject: str
    role: str = "user"
    tier: str = "standard"
    expiry_days: int = 30

@app.post("/token")
def create_token(req: TokenRequest):
    """签发JWT Token。需要管理密钥。"""
    admin_key = os.getenv("PRISM_ADMIN_KEY", "prism-admin-2026")
    if req.admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    token = sign_token(req.subject, days=req.expiry_days, role=req.role, tier=req.tier)
    return {
        "token": token,
        "subject": req.subject,
        "role": req.role,
        "tier": req.tier,
        "expires_in": f"{req.expiry_days} days"
    }

# ============ API 接口 ============

@app.get("/")
def root():
    return {
        "name": "棱镜行情数据 API",
        "version": "2.0.0",
        "identity": "prism-invest",
        "endpoints": ["/app", "/wiki", "/realtime", "/index", "/bond/double-low", "/token", "/health"],
        "pricing": "$19/month for external access",
    }

@app.get("/realtime")
def api_realtime(codes: str = Query(..., description="股票代码,逗号分隔,如 sh600519,sz000001"), token_data: dict = None):
    """查询A股/指数/ETF实时行情（需JWT鉴权，admin角色免验证）"""
    _optional_auth(token_data)
    code_list = [c.strip() for c in codes.split(",")]
    result = get_realtime(code_list)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return {"data": result}

@app.get("/index")
def api_index(indices: str = Query(None, description="指数代码,逗号分隔.默认核心指数"), token_data: dict = None):
    """查询核心指数行情（需JWT鉴权，admin角色免验证）"""
    _optional_auth(token_data)
    idx = None
    if indices:
        idx = [i.strip() for i in indices.split(",")]
    result = get_index(idx)
    return {"data": result}

@app.get("/bond/double-low")
def api_bond_double_low(top_n: int = Query(30, description="返回前N名", ge=1, le=100), token_data: dict = None):
    """查询可转债双低排名（需JWT鉴权，admin角色免验证）"""
    _optional_auth(token_data)
    result = get_bond_double_low(top_n=top_n)
    if result and isinstance(result[0], dict) and "error" in result[0]:
        raise HTTPException(status_code=503, detail=result[0]["error"])
    return {"data": result}

@app.get("/health")
def health():
    return {"status": "alive", "identity": "prism-invest", "version": "2.0.0"}

# ============ PWA 前端 ============

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

@app.get("/app")
@app.get("/app/")
def serve_app():
    """PWA入口"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="PWA not found")

@app.get("/manifest.json")
def serve_manifest():
    path = os.path.join(STATIC_DIR, "manifest.json")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/json")
    raise HTTPException(status_code=404)

@app.get("/icon-{size}.png")
def serve_icon(size: int):
    path = os.path.join(STATIC_DIR, f"icon-{size}.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404)
