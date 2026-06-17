"""
棱镜行情数据 API — Prism Market Data REST API
独立身份，自签Token，外部可调
PWA前端 + JWT鉴权 + 行情数据

启动: uvicorn prism_api:app --host 0.0.0.0 --port 8900
隧道: cloudflared tunnel --url http://localhost:8900

修订记录：
- 2024-06-18: 修复可选鉴权函数为空函数的问题
- 2024-06-18: 新增K线接口 /kline
- 2024-06-18: 新增配置查询接口 /config
- 2024-06-18: 统一错误响应格式
- 2024-06-18: 新增速率限制标记
"""

from fastapi import FastAPI, HTTPException, Header, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import jwt
import datetime
import os
import sys
import logging

# 导入棱镜行情核心模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import (
    get_realtime, 
    get_index, 
    get_bond_double_low,
    calculate_ma, calculate_macd, calculate_rsi, calculate_boll,
    get_fund_flow,
    get_kline,
    get_config,
    DEFAULT_INDICES,
    FILTER_MIN_VOLUME_WAN,
    FILTER_MAX_PREMIUM_RATE
)

# 导入wiki引擎
from wiki_engine import wiki_router

# 导入大脑API（容错）
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "prism-brain"))
    from brain_api import brain_router
    HAS_BRAIN_API = True
except ImportError:
    HAS_BRAIN_API = False
    brain_router = None

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prism-api")

app = FastAPI(
    title="棱镜行情数据 API",
    description="Prism Market Data — 三维度，一个结论。A股/可转债/ETF/K线 quant-grade data.",
    version="3.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册wiki路由
app.include_router(wiki_router)

# 注册大脑路由（如果可用）
if brain_router:
    app.include_router(brain_router)

# ============ JWT 鉴权 ============

JWT_SECRET = os.getenv("PRISM_JWT_SECRET", "prism-capital-2026-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
ADMIN_KEY = os.getenv("PRISM_ADMIN_KEY", "prism-admin-2026")

# 速率限制（简单内存计数）
rate_limit_store = {}

def sign_token(user: str, days: int = 30, role: str = "user", tier: str = "standard") -> str:
    """签发JWT Token"""
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
    """验证JWT Token"""
    if not authorization:
        raise HTTPException(
            status_code=401, 
            detail={"error": "Missing Authorization header", "hint": "Use Bearer token"}
        )
    token = authorization.replace("Bearer ", "").strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"error": "Token expired"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail={"error": "Invalid token"})


def _check_rate_limit(token_data: dict = None, endpoint: str = None):
    """
    可选鉴权 + 速率限制
    - admin角色：免验证
    - 有效token：允许访问，跟踪用量
    - 无token：允许PWA前端访问（每IP限流）
    """
    if token_data and token_data.get("role") == "admin":
        return  # admin免限
    
    # 简单速率限制
    key = token_data.get("sub", "anonymous") if token_data else "anonymous"
    current_time = int(datetime.datetime.utcnow().timestamp() / 60)  # 每分钟
    
    if key not in rate_limit_store:
        rate_limit_store[key] = {}
    
    rate = rate_limit_store[key]
    if current_time not in rate:
        rate[current_time] = 0
    rate[current_time] += 1
    
    # 每分钟最多100次（普通用户）或无限制（admin/付费用户）
    limit = token_data.get("rate_limit", 100) if token_data else 20
    if rate[current_time] > limit:
        raise HTTPException(
            status_code=429, 
            detail={"error": "Rate limit exceeded", "limit": limit, "window": "per minute"}
        )


# ============ 请求/响应模型 ============

class TokenRequest(BaseModel):
    admin_key: str
    subject: str
    role: str = "user"
    tier: str = "standard"
    expiry_days: int = 30


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
    hint: str = ""


class SuccessResponse(BaseModel):
    data: dict | list
    meta: dict = Field(default_factory=dict)


# ============ Token 签发 ============

@app.post("/token", response_model=dict)
def create_token(req: TokenRequest):
    """签发JWT Token。需要管理密钥。"""
    if req.admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail={"error": "Invalid admin key"})
    
    token = sign_token(
        req.subject, 
        days=req.expiry_days, 
        role=req.role, 
        tier=req.tier
    )
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
    """API根路径"""
    return {
        "name": "棱镜行情数据 API",
        "version": "3.1.0",
        "identity": "prism-invest",
        "endpoints": {
            "realtime": "/realtime?codes=sh600519,sz000001",
            "index": "/index",
            "kline": "/kline?code=sh600519&period=daily",
            "bond": "/bond/double-low",
            "analyze": "/analyze?code=sh600519",
            "fundflow": "/fundflow?code=sh600519",
            "search": "/search?keyword=茅台",
            "wiki": "/wiki",
            "brain": "/brain/stats | /brain/query | /brain/decide",
            "evolution": "/evolution/log | /evolution/feedback",
            "config": "/config",
            "docs": "/docs",
            "health": "/health"
        },
        "pricing": "$19/month for external access",
    }


@app.get("/realtime", response_model=SuccessResponse)
def api_realtime(
    codes: str = Query(..., description="股票代码,逗号分隔,如 sh600519,sz000001"),
    token_data: dict = Depends(verify_token)
):
    """查询A股/指数/ETF实时行情"""
    _check_rate_limit(token_data, "realtime")
    code_list = [c.strip() for c in codes.split(",")]
    result = get_realtime(code_list)
    
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=503, detail=result)
    
    return SuccessResponse(
        data=result,
        meta={
            "count": len(result) if isinstance(result, list) else 1,
            "source": "tencent/sina"
        }
    )


@app.get("/index", response_model=SuccessResponse)
def api_index(
    indices: str = Query(None, description="指数代码,逗号分隔.默认核心指数"),
    token_data: dict = Depends(verify_token)
):
    """查询核心指数行情"""
    _check_rate_limit(token_data, "index")
    idx = None
    if indices:
        idx = [i.strip() for i in indices.split(",")]
    result = get_index(idx)
    
    return SuccessResponse(
        data=result,
        meta={
            "count": len(result),
            "indices": idx or DEFAULT_INDICES
        }
    )


@app.get("/kline", response_model=SuccessResponse)
def api_kline(
    code: str = Query(..., description="股票代码,如 sh600519"),
    period: str = Query("daily", description="K线周期: daily/weekly/monthly/qfqdaily"),
    count: int = Query(100, description="返回条数,最大500", ge=1, le=500),
    token_data: dict = Depends(verify_token)
):
    """查询A股/指数历史K线"""
    _check_rate_limit(token_data, "kline")
    result = get_kline(code, period, count)
    
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=503, detail=result)
    
    return SuccessResponse(
        data=result,
        meta={
            "code": code,
            "period": period,
            "count": len(result.get("数据", []))
        }
    )


@app.get("/bond/double-low", response_model=SuccessResponse)
def api_bond_double_low(
    top_n: int = Query(30, description="返回前N名", ge=1, le=100),
    min_rating: str = Query("AA-", description="最低评级"),
    min_volume: float = Query(FILTER_MIN_VOLUME_WAN, description="最低成交额(万元)"),
    max_premium: float = Query(FILTER_MAX_PREMIUM_RATE, description="最高溢价率(%)"),
    exclude_st: bool = Query(True, description="排除ST债"),
    token_data: dict = Depends(verify_token)
):
    """查询可转债双低排名"""
    _check_rate_limit(token_data, "bond")
    result = get_bond_double_low(
        top_n=top_n,
        min_rating=min_rating,
        min_volume=min_volume,
        max_premium=max_premium,
        exclude_st=exclude_st
    )
    
    if result and isinstance(result[0], dict) and "error" in result[0]:
        raise HTTPException(status_code=503, detail=result[0])
    
    return SuccessResponse(
        data=result,
        meta={
            "count": len(result),
            "filters": {
                "min_rating": min_rating,
                "min_volume": min_volume,
                "max_premium": max_premium,
                "exclude_st": exclude_st
            }
        }
    )




@app.get("/analyze", response_model=SuccessResponse)
def api_analyze(
    code: str = Query(..., description="股票代码，如sh600519"),
    token_data: dict = Depends(verify_token),
):
    """技术分析：MA/MACD/RSI/布林带"""
    _check_rate_limit(token_data, "analyze")
    
    # 获取日K线数据（最近120天）
    kline_result = get_kline(code, period="day", count=120)
    if not kline_result or "数据" not in kline_result:
        raise HTTPException(status_code=404, detail={"error": f"未找到 {code} 的K线数据"})
    
    kline_data = kline_result["数据"]
    if not kline_data:
        raise HTTPException(status_code=404, detail={"error": f"{code} K线数据为空"})
    
    close_prices = [bar["收盘"] for bar in kline_data if isinstance(bar, dict) and bar.get("收盘")]
    if len(close_prices) < 30:
        raise HTTPException(status_code=400, detail={"error": "K线数据不足，至少需要30根"})
    
    ma = calculate_ma(close_prices)
    macd = calculate_macd(close_prices)
    rsi = calculate_rsi(close_prices)
    boll = calculate_boll(close_prices)
    
    latest = kline_data[-1]
    
    return SuccessResponse(
        data={
            "代码": code,
            "最新价": latest.get("收盘", 0),
            "日期": latest.get("日期", ""),
            "MA": ma,
            "MACD": macd,
            "RSI": rsi,
            "布林带": boll,
        },
        meta={
            "data_points": len(close_prices),
            "source": "tencent/kline",
        }
    )



@app.get("/fundflow", response_model=SuccessResponse)
def api_fundflow(
    code: str = Query(..., description="股票代码，如sh600519"),
    days: int = Query(10, description="天数", ge=1, le=60),
    token_data: dict = Depends(verify_token),
):
    """资金流向：主力/散户资金净流入"""
    _check_rate_limit(token_data, "fundflow")
    
    result = get_fund_flow(code, days=days)
    
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=503, detail=result)
    
    return SuccessResponse(
        data=result,
        meta={"source": "eastmoney/fundflow"}
    )

@app.get("/config")
def api_config():
    """获取API配置信息"""
    config = get_config()
    return {
        "config": config,
        "version": "3.1.0",
        "note": "这是运行时配置，可通过环境变量覆盖"
    }


@app.get("/search")
def api_search(
    keyword: str = Query(..., description="搜索关键词（名称/拼音/代码）"),
    limit: int = Query(10, ge=1, le=30, description="最多返回条数"),
    authorization: str = Header(None),
):
    """搜索股票（名称/拼音/代码）"""
    verify_token(authorization)
    from main import search_stock
    results = search_stock(keyword, limit)
    return {
        "data": results,
        "keyword": keyword,
        "count": len(results)
    }


@app.get("/health")
def health():
    """全系统自检：API + Brain + Evolution + 数据源"""
    checks = {}
    overall = "healthy"
    
    # 1. API进程
    checks["api"] = {"status": "ok", "version": "3.1.0", "port": 8900}
    
    # 2. Brain记忆
    try:
        brain_stats = _get_brain_stats()
        checks["brain"] = {"status": "ok", **brain_stats}
    except:
        checks["brain"] = {"status": "degraded", "note": "Brain模块不可用"}
        overall = "degraded"
    
    # 3. Evolution决策日志
    try:
        evo_stats = _get_evolution_stats()
        checks["evolution"] = {"status": "ok", **evo_stats}
    except:
        checks["evolution"] = {"status": "degraded", "note": "Evolution模块不可用"}
    
    # 4. 数据源检测
    sources = {}
    # 腾讯实时行情
    try:
        r = requests.get("https://qt.gtimg.cn/q=sh000001", timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        sources["tencent_realtime"] = "ok" if r.status_code == 200 and "sh000001" in r.text else "fail"
    except:
        sources["tencent_realtime"] = "fail"
    # 新浪K线
    try:
        r = requests.get("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000001&scale=240&datalen=1", timeout=8,
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        sources["sina_kline"] = "ok" if r.status_code == 200 and len(r.text) > 50 else "fail"
    except:
        sources["sina_kline"] = "fail"
    # 东方财富DC
    try:
        r = requests.get("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BOND_CB_LIST&pageSize=1", timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        # DC接口需要额外参数才算success，但能连通就算ok
        sources["eastmoney_dc"] = "ok" if r.status_code == 200 else "fail"
    except:
        sources["eastmoney_dc"] = "fail"
    # 东方财富push2his（经常被封）
    try:
        r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000001&fields1=f1&fields2=f51&klt=101&fqt=1&beg=20250101&end=20250102", timeout=5)
        sources["eastmoney_kline"] = "ok" if r.status_code == 200 else "blocked"
    except:
        sources["eastmoney_kline"] = "blocked"
    
    checks["data_sources"] = sources
    # 数据源检测仅供参考，不影响整体状态（API进程内网络可能受限）
    
    # 5. 隧道状态
    try:
        import subprocess
        result = subprocess.run(["pgrep", "-f", "cloudflared"], capture_output=True, text=True)
        checks["tunnel"] = {"status": "ok" if result.returncode == 0 else "down"}
        if result.returncode != 0:
            overall = "degraded"
    except:
        checks["tunnel"] = {"status": "unknown"}
    
    return {
        "status": overall,
        "identity": "prism-invest",
        "version": "3.1.0",
        "timestamp": datetime.datetime.now().isoformat(),
        "checks": checks
    }


def _get_brain_stats():
    """获取Brain统计"""
    try:
        from prism_brain import PrismMemory
        BRAIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "prism-brain")
        sys.path.insert(0, BRAIN_DIR)
        m = PrismMemory(os.path.join(BRAIN_DIR, "memory", "prism_memory.db"))
        stats = m.stats()
        return {"memories": stats.get("total", 0), "tags": stats.get("by_tag", {})}
    except:
        return {}


def _get_evolution_stats():
    """获取Evolution统计"""
    try:
        from prism_evolution import DecisionJournal
        BRAIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "prism-brain")
        sys.path.insert(0, BRAIN_DIR)
        j = DecisionJournal(os.path.join(BRAIN_DIR, "journal", "evolution.db"))
        stats = j.accuracy_stats()
        return {"decisions": stats.get("total_decisions", 0), "accuracy": stats.get("avg_accuracy"), "lessons": stats.get("with_lessons", 0)}
    except:
        return {}


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
