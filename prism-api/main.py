"""
棱镜行情数据 - Prism Market Data API
棱镜投资决策系统专属行情数据接口

数据源：
- 腾讯财经(qt.gtimg.cn) 主力源 — 实时行情（GBK编码）
- 新浪财经(hq.sinajs.cn) 备用源 — 实时行情
- efinance — 可转债基础列表（代码/评级/正股/转股价）
- 腾讯财经批量 — 可转债实时价格

策略：efinance拿基础信息 → 腾讯批量获取实时行情 → 本地计算双低值

修订记录：
- 2024-06-18: 修复历史K线功能缺失问题，新增get_kline函数
- 2024-06-18: 修复双低值计算问题，新增转股价获取和精确双低值计算
- 2024-06-18: 统一API返回格式，补全新浪源缺失字段
- 2024-06-18: 新增配置项常量，支持环境变量覆盖
- 2024-06-18: 增强错误处理，记录详细错误日志
"""

import json
import re
import os
import time
import logging
from typing import List, Dict, Optional, Union
import requests

# ============ 配置项（支持环境变量覆盖） ============

TENCENT_URL = os.getenv("PRISM_TENCENT_URL", "http://qt.gtimg.cn/q={codes}")
SINA_URL = os.getenv("PRISM_SINA_URL", "http://hq.sinajs.cn/list={codes}")
EFINANCE_URL = os.getenv("PRISM_EFINANCE_URL", None)  # efinance使用内置源

TIMEOUT_PRIMARY = float(os.getenv("PRISM_TIMEOUT_PRIMARY", "3"))  # 主源超时秒数
TIMEOUT_SECONDARY = float(os.getenv("PRISM_TIMEOUT_SECONDARY", "5"))  # 备用源超时秒数
MAX_RETRIES = int(os.getenv("PRISM_MAX_RETRIES", "2"))  # 最大重试次数

BATCH_SIZE_REALTIME = int(os.getenv("PRISM_BATCH_SIZE_REALTIME", "50"))  # 实时行情批量大小
BATCH_SIZE_BOND = int(os.getenv("PRISM_BATCH_SIZE_BOND", "30"))  # 可转债批量大小

# 棱镜筛选标准（可配置）
FILTER_MIN_RATING_SCORE = 3  # AA-及以上
FILTER_MIN_VOLUME_WAN = 500  # 成交额下限（万元）
FILTER_MAX_PREMIUM_RATE = 50  # 溢价率上限（%）

# 默认核心指数列表
DEFAULT_INDICES = [
    "sh000300",  # 沪深300
    "sz399006",  # 创业板指
    "sh000016",  # 上证50
    "sh000905",  # 中证500
    "sh000001",  # 上证指数
    "sz399001",  # 深证成指
]

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prism-market-data")


# ============ 实时行情 ============

def get_realtime(codes) -> Union[Dict, List[Dict]]:
    """
    查询A股/指数/ETF实时行情
    
    参数:
        codes: 单个代码字符串如"sh600519"，或列表如["sh600519","sz000001"]
               沪市前缀sh，深市前缀sz，指数如sh000300
    返回:
        单个代码返回dict，多个代码返回list[dict]
        统一返回字段：代码、名称、现价、昨收、今开、成交量、成交额、
                    涨跌额、涨跌幅、最高、最低、换手率、市盈率、总市值、流通市值、状态
    """
    if isinstance(codes, str):
        codes = [codes]
        single = True
    else:
        single = False
    
    # 尝试腾讯源（带重试）
    result = _fetch_tencent(codes)
    if result is None:
        # 备用：新浪源
        logger.warning("腾讯源失败，切换到新浪源")
        result = _fetch_sina(codes)
    
    if result is None:
        logger.error("所有数据源均失败")
        return {"error": "所有数据源均失败", "codes": codes}
    
    # 统一返回格式：补全缺失字段
    result = _normalize_realtime_result(result)
    
    if single:
        return result[0] if result else {}
    return result


def _fetch_tencent(codes: List[str], retries: int = None) -> Optional[List[Dict]]:
    """腾讯财经实时行情（主力源）"""
    if retries is None:
        retries = MAX_RETRIES
    
    for attempt in range(retries + 1):
        try:
            code_str = ",".join(codes)
            url = TENCENT_URL.format(codes=code_str)
            resp = requests.get(url, timeout=TIMEOUT_PRIMARY)
            if resp.status_code != 200:
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                return None
            
            text = resp.content.decode('gbk', errors='replace')
            items = []
            for line in text.strip().split(";"):
                line = line.strip()
                if not line or '=""' in line or "pv_none" in line:
                    continue
                match = re.match(r'v_(\w+)="(.+)"', line)
                if not match:
                    continue
                
                fields = match.group(2).split("~")
                if len(fields) < 48:
                    continue
                
                try:
                    item = _parse_tencent_field(fields)
                    if item:
                        items.append(item)
                except (IndexError, ValueError) as e:
                    logger.debug(f"解析腾讯字段失败: {e}")
                    continue
            
            return items if items else None
        except requests.exceptions.Timeout:
            logger.warning(f"腾讯源超时 (尝试 {attempt + 1}/{retries + 1})")
            if attempt < retries:
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"腾讯源异常: {type(e).__name__}: {e}")
            return None
    
    return None


def _parse_tencent_field(fields: List[str]) -> Optional[Dict]:
    """解析腾讯财经字段"""
    item = {
        "代码": fields[2],
        "名称": fields[1],
        "现价": _safe_float(fields[3]),
        "昨收": _safe_float(fields[4]),
        "今开": _safe_float(fields[5]),
        "成交量": _safe_int(fields[6]),
        "成交额": _safe_float(fields[37]) if len(fields) > 37 else 0,
        "涨跌额": _safe_float(fields[31]),
        "涨跌幅": _safe_float(fields[32]),
        "最高": _safe_float(fields[33]),
        "最低": _safe_float(fields[34]),
        "换手率": _safe_float(fields[38]) if len(fields) > 38 else 0,
        "市盈率": _safe_float(fields[39]) if len(fields) > 39 else 0,
        "总市值": _safe_float(fields[45]) if len(fields) > 45 else 0,
        "流通市值": _safe_float(fields[44]) if len(fields) > 44 else 0,
    }
    if item["现价"] == 0 and item["成交量"] == 0:
        item["状态"] = "停牌"
    return item


def _fetch_sina(codes: List[str]) -> Optional[List[Dict]]:
    """新浪财经实时行情（备用源）"""
    items = []
    for code in codes:
        try:
            url = SINA_URL.format(codes=code)
            headers = {"Referer": "https://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=TIMEOUT_PRIMARY)
            if resp.status_code != 200:
                continue
            
            text = resp.content.decode('gbk', errors='replace')
            match = re.search(r'="(.+)"', text)
            if not match:
                continue
            
            fields = match.group(1).split(",")
            if len(fields) < 10:
                continue
            
            item = _parse_sina_field(code, fields)
            if item:
                items.append(item)
        except Exception as e:
            logger.debug(f"解析新浪字段失败: {code} - {e}")
            continue
    
    return items if items else None


def _parse_sina_field(code: str, fields: List[str]) -> Optional[Dict]:
    """解析新浪财经字段，返回统一格式"""
    try:
        open_price = _safe_float(fields[1])
        prev_close = _safe_float(fields[2])
        current = _safe_float(fields[3])
        high = _safe_float(fields[4])
        low = _safe_float(fields[5])
        volume = _safe_int(fields[8])
        amount = _safe_float(fields[9])
        
        change = round(current - prev_close, 2) if current > 0 and prev_close > 0 else 0
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0
        
        item = {
            "代码": code[2:],
            "名称": fields[0],
            "现价": current,
            "昨收": prev_close,
            "今开": open_price,
            "成交量": volume,
            "成交额": amount,
            "涨跌额": change,
            "涨跌幅": change_pct,
            "最高": high,
            "最低": low,
            # 以下为补全字段（新浪源缺失）
            "换手率": 0,
            "市盈率": 0,
            "总市值": 0,
            "流通市值": 0,
        }
        if current == 0 and volume == 0:
            item["状态"] = "停牌"
        return item
    except (IndexError, ValueError):
        return None


def _normalize_realtime_result(items: List[Dict]) -> List[Dict]:
    """统一实时行情返回格式，补全缺失字段"""
    standard_keys = [
        "代码", "名称", "现价", "昨收", "今开", "成交量", "成交额",
        "涨跌额", "涨跌幅", "最高", "最低", "换手率", "市盈率",
        "总市值", "流通市值", "状态"
    ]
    normalized = []
    for item in items:
        norm_item = {}
        for key in standard_keys:
            norm_item[key] = item.get(key, 0 if key != "名称" and key != "代码" and key != "状态" else "-")
        normalized.append(norm_item)
    return normalized


# ============ 历史K线（新增） ============

def get_kline(code: str, period: str = "daily", count: int = 100) -> Dict:
    """
    查询A股/指数历史K线
    
    参数:
        code: 股票代码，如"sh600519"
        period: K线周期，支持 daily/weekly/monthly/qfqdaily（默认日线）
        count: 返回数量，默认100条，最多500条
    返回:
        {
            "代码": str,
            "名称": str,
            "周期": str,
            "数据": [{"日期": str, "开盘": float, "收盘": float, "最高": float, "最低": float, "成交量": int, "成交额": float, "涨跌幅": float}, ...],
            "更新时间": str
        }
    """
    valid_periods = {
        "daily": "日K",
        "weekly": "周K", 
        "monthly": "月K",
        "qfqdaily": "前复权日K"
    }
    period_name = valid_periods.get(period, "日K")
    count = min(count, 500)  # 限制最大500条
    
    try:
        import efinance as ef
    except ImportError:
        return {"error": "缺少efinance库，请pip install efinance"}
    
    try:
        # 获取股票基本信息
        basic = get_realtime(code)
        stock_name = basic.get("名称", code) if isinstance(basic, dict) else code
        
        # 获取K线数据（efinance正确方法名）
        sec_code = code[2:] if code.startswith(("sh", "sz")) else code  # 去掉sh/sz前缀
        klt_map = {"daily": 101, "weekly": 102, "monthly": 103, "qfqdaily": 101}
        klt = klt_map.get(period, 101)
        df = ef.stock.get_quote_history(sec_code, klt=klt)
        
        if df is None or df.empty:
            return {"error": f"获取{period_name}数据失败"}
        
        # 取最近count条
        df = df.tail(count)
        
        # 转换为统一格式
        data = []
        for _, row in df.iterrows():
            # efinance列名可能不同，尝试兼容
            date = str(row.get('日期', row.get('时间', '')))
            open_price = _safe_float(row.get('开盘', row.get('开', 0)))
            close_price = _safe_float(row.get('收盘', row.get('收', 0)))
            high_price = _safe_float(row.get('最高', row.get('高', 0)))
            low_price = _safe_float(row.get('最低', row.get('低', 0)))
            volume = _safe_int(row.get('成交量', row.get('VOL', 0)))
            amount = _safe_float(row.get('成交额', row.get('Amount', 0)))
            
            # 计算涨跌幅（如果没有直接字段）
            change_pct = _safe_float(row.get('涨跌幅', 0))
            if change_pct == 0 and len(data) > 0:
                prev_close = data[-1]['收盘']
                if prev_close > 0:
                    change_pct = round((close_price - prev_close) / prev_close * 100, 2)
            
            data.append({
                "日期": date,
                "开盘": open_price,
                "收盘": close_price,
                "最高": high_price,
                "最低": low_price,
                "成交量": volume,
                "成交额": amount,
                "涨跌幅": change_pct
            })
        
        return {
            "代码": code,
            "名称": stock_name,
            "周期": period_name,
            "数据": data,
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    except Exception as e:
        logger.warning(f"efinance K线失败，切换新浪源: {code} - {e}")
        # fallback: 新浪财经K线
        result = _get_kline_sina(code, period, count)
        if result and "error" not in result:
            return result
        return {"error": f"获取K线失败: {str(e)}"}


def _get_kline_sina(code: str, period: str = "daily", count: int = 100) -> Dict:
    """新浪财经K线数据（东方财富失败时的备用源）"""
    try:
        # 新浪需要不带前缀的6位代码
        raw_code = code[2:] if code.startswith(("sh", "sz")) else code
        prefix = code[:2] if code.startswith(("sh", "sz")) else ("sh" if raw_code.startswith(("5","6","9")) else "sz")
        sina_code = f"{prefix}{raw_code}"
        
        # scale: 240=日线, 1200=周线, 7200=月线
        scale_map = {"daily": "240", "weekly": "1200", "monthly": "7200", "qfqdaily": "240"}
        scale = scale_map.get(period, "240")
        
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {"symbol": sina_code, "scale": scale, "ma": "no", "datalen": str(min(count, 500))}
        
        resp = requests.get(url, params=params, timeout=10, headers={"Referer": "https://finance.sina.com.cn"})
        if resp.status_code != 200 or not resp.text.strip():
            return {"error": "新浪K线数据为空"}
        
        raw_data = json.loads(resp.text)
        if not isinstance(raw_data, list) or len(raw_data) == 0:
            return {"error": "新浪K线解析失败"}
        
        data = []
        for bar in raw_data:
            close_p = _safe_float(bar.get("close", 0))
            open_p = _safe_float(bar.get("open", 0))
            high_p = _safe_float(bar.get("high", 0))
            low_p = _safe_float(bar.get("low", 0))
            vol = _safe_int(bar.get("volume", 0))
            change_pct = round((close_p - open_p) / open_p * 100, 2) if open_p > 0 else 0
            if len(data) > 0:
                prev_close = data[-1]["收盘"]
                if prev_close > 0:
                    change_pct = round((close_p - prev_close) / prev_close * 100, 2)
            data.append({
                "日期": bar.get("day", ""),
                "开盘": open_p,
                "收盘": close_p,
                "最高": high_p,
                "最低": low_p,
                "成交量": vol,
                "成交额": 0,
                "涨跌幅": change_pct
            })
        
        # 获取名称
        try:
            basic = get_realtime(code)
            stock_name = basic.get("名称", code) if isinstance(basic, dict) else code
        except:
            stock_name = code
        
        period_names = {"daily": "日K", "weekly": "周K", "monthly": "月K", "qfqdaily": "前复权日K"}
        
        return {
            "代码": code,
            "名称": stock_name,
            "周期": period_names.get(period, "日K"),
            "数据": data,
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "数据源": "sina_fallback"
        }
    except Exception as e:
        logger.error(f"新浪K线也失败: {code} - {e}")
        return {"error": f"新浪K线fallback失败: {str(e)}"}


# ============ 指数行情 ============

def get_index(indices: List[str] = None) -> List[Dict]:
    """
    查询指数行情
    
    参数:
        indices: 指数代码列表，默认查询核心指数
                 sh000300=沪深300, sz399006=创业板指, sh000016=上证50
                 sh000905=中证500, sh000001=上证指数, sz399001=深证成指
    返回:
        list[dict]
    """
    if indices is None:
        indices = DEFAULT_INDICES.copy()
    return get_realtime(indices)


# ============ 可转债双低排名 ============

def get_bond_double_low(
    top_n: int = 30,
    min_rating: str = "AA-",
    min_volume: float = 500,
    max_premium: float = 50,
    exclude_st: bool = True
) -> List[Dict]:
    """
    查询可转债双低排名
    
    策略：efinance获取可转债基础列表(评级/正股/转股价) → 腾讯批量获取实时行情 → 计算双低值
    
    参数:
        top_n: 返回前N名，默认30
        min_rating: 最低评级要求，默认AA-
        min_volume: 最低成交额（万元），默认500万
        max_premium: 最高溢价率（%），默认50%
        exclude_st: 是否排除ST债，默认True
    返回:
        list[dict] 按双低值升序排列，已过滤棱镜标准
    """
    try:
        import efinance as ef
        import pandas as pd
    except ImportError:
        return [{"error": "缺少efinance库，请pip install efinance"}]
    
    try:
        # Step 1: 获取可转债基础信息（包含转股价）
        df_base = ef.bond.get_all_base_info()
        if df_base is None or df_base.empty:
            return [{"error": "可转债基础信息获取失败"}]
        
        # 只保留已上市的（有上市日期）
        listed = df_base[df_base['上市日期'].notna()].copy()
        
        # 清理评级字段
        listed['债券评级_clean'] = listed['债券评级'].astype(str).str.replace('sti', '', regex=False).str.strip()
        
        # 构建腾讯代码
        listed['qt_code'] = listed['债券代码'].apply(
            lambda x: f"sh{x}" if str(x).startswith('11') else f"sz{x}"
        )
        
        # Step 2: 批量获取实时行情
        all_bonds = []
        code_list = listed['qt_code'].tolist()
        
        for i in range(0, len(code_list), BATCH_SIZE_BOND):
            batch = code_list[i:i+BATCH_SIZE_BOND]
            batch_data = _fetch_bond_batch(batch, listed)
            all_bonds.extend(batch_data)
        
        if not all_bonds:
            return [{"error": "可转债实时行情获取失败"}]
        
        # Step 2.5: 获取转股价数据（东方财富数据中心）
        convert_prices = _fetch_convert_prices()
        # 将转股价注入到all_bonds中
        for b in all_bonds:
            code = b.get("代码", "")
            if code in convert_prices:
                b["转股价"] = convert_prices[code]
        
        # Step 3: 获取正股价格
        stock_prices = _fetch_stock_prices(all_bonds)
        
        # Step 4: 计算转股溢价率和双低值
        for b in all_bonds:
            _calculate_premium_and_double_low(b, stock_prices)
        
        # Step 5: 应用筛选条件
        filtered = _filter_bonds(
            all_bonds, 
            min_rating=min_rating,
            min_volume=min_volume,
            max_premium=max_premium,
            exclude_st=exclude_st
        )
        
        # 按双低值升序排列
        filtered.sort(key=lambda x: x.get("双低值", 9999) if isinstance(x.get("双低值"), (int, float)) else 9999)
        
        return filtered[:top_n]
    
    except Exception as e:
        logger.error(f"可转债数据获取失败: {e}")
        return [{"error": f"可转债数据获取失败: {str(e)}"}]


def _fetch_bond_batch(batch: List[str], listed_df: 'DataFrame') -> List[Dict]:
    import pandas as pd
    """批量获取可转债行情"""
    bonds = []
    try:
        batch_str = ",".join(batch)
        url = f"http://qt.gtimg.cn/q={batch_str}"
        resp = requests.get(url, timeout=TIMEOUT_SECONDARY)
        if resp.status_code != 200:
            return bonds
        
        text = resp.content.decode('gbk', errors='replace')
        
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or '=""' in line or "pv_none" in line:
                continue
            match = re.match(r'v_(\w+)="(.+)"', line)
            if not match:
                continue
            
            fields = match.group(2).split("~")
            if len(fields) < 48:
                continue
            
            try:
                bond_code = fields[2]
                bond_name = fields[1]
                price = _safe_float(fields[3])
                change_pct = _safe_float(fields[32])
                volume = _safe_float(fields[37]) if len(fields) > 37 else 0
                turnover = _safe_float(fields[38]) if len(fields) > 38 else 0
                
                if price <= 0:
                    continue
                
                # 从基础信息中匹配
                row = listed_df[listed_df['债券代码'] == bond_code]
                if len(row) == 0:
                    continue
                
                rating = row['债券评级_clean'].values[0]
                stock_code = str(row['正股代码'].values[0])
                stock_name = str(row['正股名称'].values[0])
                # 获取转股价（关键！）
                convert_price = row.get('转股价', pd.Series([None])).values[0]
                if pd.isna(convert_price):
                    convert_price = row.get('转股价格', pd.Series([None])).values[0]
                
                bonds.append({
                    "代码": bond_code,
                    "名称": bond_name,
                    "价格": price,
                    "涨跌幅": change_pct,
                    "成交额(万)": round(volume / 10000, 2) if volume > 10000 else round(volume, 2),
                    "换手率": turnover,
                    "评级": rating,
                    "正股代码": stock_code,
                    "正股名称": stock_name,
                    "转股价": _safe_float(convert_price) if convert_price else 0,
                })
            except Exception as e:
                logger.debug(f"解析可转债字段失败: {e}")
                continue
    
    except Exception as e:
        logger.warning(f"批量获取可转债行情失败: {e}")
    
    return bonds






# ============ 技术分析模块 ============

def calculate_ma(prices: list, periods: list = [5, 10, 20, 60]) -> dict:
    """计算移动平均线"""
    result = {}
    for p in periods:
        if len(prices) >= p:
            result[f"MA{p}"] = round(sum(prices[-p:]) / p, 2)
        else:
            result[f"MA{p}"] = None
    return result


def calculate_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算MACD指标"""
    if len(prices) < slow + signal:
        return {"MACD": None, "Signal": None, "Histogram": None, "趋势": "数据不足"}
    
    # EMA计算
    def ema(data, period):
        multiplier = 2 / (period + 1)
        result = [data[0]]
        for price in data[1:]:
            result.append((price - result[-1]) * multiplier + result[-1])
        return result
    
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    
    dea = ema(dif, signal)
    histogram = [d - e for d, e in zip(dif, dea)]
    
    trend = "多头" if dif[-1] > dea[-1] else "空头"
    if len(histogram) >= 2:
        if histogram[-1] > histogram[-2] > 0:
            trend = "多头加速"
        elif 0 < histogram[-1] < histogram[-2]:
            trend = "多头衰减"
        elif histogram[-1] < histogram[-2] < 0:
            trend = "空头加速"
        elif 0 > histogram[-1] > histogram[-2]:
            trend = "空头衰减"
    
    return {
        "DIF": round(dif[-1], 3),
        "DEA": round(dea[-1], 3),
        "MACD柱": round(histogram[-1] * 2, 3),
        "趋势": trend,
    }


def calculate_rsi(prices: list, period: int = 14) -> dict:
    """计算RSI指标"""
    if len(prices) < period + 1:
        return {"RSI": None, "状态": "数据不足"}
    
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(c, 0) for c in changes[-period:]]
    losses = [max(-c, 0) for c in changes[-period:]]
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    
    if rsi > 80:
        state = "严重超买"
    elif rsi > 70:
        state = "超买"
    elif rsi > 60:
        state = "偏强"
    elif rsi > 40:
        state = "中性"
    elif rsi > 30:
        state = "偏弱"
    elif rsi > 20:
        state = "超卖"
    else:
        state = "严重超卖"
    
    return {
        "RSI": round(rsi, 2),
        "状态": state,
    }


def calculate_boll(prices: list, period: int = 20, std_dev: float = 2.0) -> dict:
    """计算布林带"""
    if len(prices) < period:
        return {"上轨": None, "中轨": None, "下轨": None, "位置": "数据不足"}
    
    import statistics
    slice_prices = prices[-period:]
    mid = sum(slice_prices) / period
    std = statistics.stdev(slice_prices)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    current = prices[-1]
    
    if current > upper:
        pos = "突破上轨"
    elif current > mid:
        pos = "中上区间"
    elif current > lower:
        pos = "中下区间"
    else:
        pos = "跌破下轨"
    
    return {
        "上轨": round(upper, 2),
        "中轨": round(mid, 2),
        "下轨": round(lower, 2),
        "位置": pos,
        "带宽": round((upper - lower) / mid * 100, 2),
    }



def get_fund_flow(code: str, days: int = 10) -> dict:
    """获取个股资金流向（东方财富）
    
    参数:
        code: 股票代码，如sh600519
        days: 返回天数，默认10
    """
    # 转换代码格式
    raw_code = code.replace('sh', '').replace('sz', '')
    prefix = '1' if code.startswith('sh') or code.startswith('6') else '0'
    secid = f"{prefix}.{raw_code}"
    
    try:
        url = 'http://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get'
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'lmt': days,
            'klt': 101,
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://data.eastmoney.com/',
        }
        session = requests.Session()
        session.headers.update(headers)
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        resp = session.get(url, params=params, timeout=10)
        data = resp.json()
        
        if not data.get('data') or not data['data'].get('klines'):
            return {"error": f"未找到 {code} 的资金流向数据"}
        
        flows = []
        for line in data['data']['klines']:
            fields = line.split(',')
            if len(fields) >= 11:
                flows.append({
                    "日期": fields[0],
                    "主力净流入": round(_safe_float(fields[1]) / 1e8, 2),  # 亿元
                    "小单净流入": round(_safe_float(fields[2]) / 1e8, 2),
                    "中单净流入": round(_safe_float(fields[3]) / 1e8, 2),
                    "大单净流入": round(_safe_float(fields[4]) / 1e8, 2),
                    "超大单净流入": round(_safe_float(fields[5]) / 1e8, 2),
                    "主力净流入占比": _safe_float(fields[6]),
                })
        
        # 计算汇总
        total_main = sum(f["主力净流入"] for f in flows)
        latest = flows[-1] if flows else {}
        
        return {
            "代码": code,
            "最新日期": latest.get("日期", ""),
            "最新主力净流入(亿)": latest.get("主力净流入", 0),
            f"近{days}日主力净流入(亿)": round(total_main, 2),
            "主力方向": "净流入" if total_main > 0 else "净流出",
            "明细": flows,
        }
    except Exception as e:
        return {"error": f"资金流向获取失败: {e}"}

def _fetch_convert_prices() -> dict:
    """从东方财富数据中心获取可转债初始转股价
    注：这是初始转股价，未下修的转债=当前转股价；下修过的会有偏差
    TODO: 接入集思录获取当前转股价
    """
    convert_prices = {}
    page = 1
    try:
        while True:
            url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
            params = {
                'reportName': 'RPT_BOND_CB_LIST',
                'columns': 'SECURITY_CODE,INITIAL_TRANSFER_PRICE',
                'pageSize': 500,
                'pageNumber': page,
                'sortColumns': 'SECURITY_CODE',
                'sortTypes': 1,
            }
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            if not data.get('result') or not data['result'].get('data'):
                break
            for item in data['result']['data']:
                code = item.get('SECURITY_CODE', '')
                itp = item.get('INITIAL_TRANSFER_PRICE')
                if code and itp:
                    convert_prices[code] = float(itp)
            if len(data['result']['data']) < 500:
                break
            page += 1
    except Exception as e:
        logger.warning(f"获取转股价数据失败: {e}")
    return convert_prices

def _fetch_stock_prices(bonds: List[Dict]) -> Dict[str, float]:
    """批量获取正股价格"""
    stock_prices = {}
    stock_codes_set = set()
    
    for b in bonds:
        sc = b.get("正股代码", "")
        if sc and sc != "nan" and len(sc) == 6:
            prefix = "sh" if sc.startswith(('6', '5')) else "sz"
            stock_codes_set.add(f"{prefix}{sc}")
    
    valid_stocks = list(stock_codes_set)
    for i in range(0, len(valid_stocks), BATCH_SIZE_REALTIME):
        batch = valid_stocks[i:i+BATCH_SIZE_REALTIME]
        batch_str = ",".join(batch)
        try:
            url = f"http://qt.gtimg.cn/q={batch_str}"
            resp = requests.get(url, timeout=TIMEOUT_SECONDARY)
            text = resp.content.decode('gbk', errors='replace')
            
            for line in text.strip().split(";"):
                line = line.strip()
                if not line:
                    continue
                m = re.match(r'v_(\w+)="(.+)"', line)
                if m:
                    fs = m.group(2).split("~")
                    if len(fs) > 3:
                        stock_prices[fs[2]] = _safe_float(fs[3])
        except Exception as e:
            logger.debug(f"获取正股价格失败: {e}")
            continue
    
    return stock_prices


def _calculate_premium_and_double_low(bond: Dict, stock_prices: Dict[str, float]):
    """计算转股溢价率和双低值"""
    price = bond.get("价格", 0)
    stock_price = stock_prices.get(bond.get("正股代码", ""), 0)
    convert_price = bond.get("转股价", 0)
    
    bond["正股价格"] = stock_price
    
    # 计算转股溢价率
    if price > 0 and stock_price > 0 and convert_price > 0:
        # 转股价值 = (正股价格 / 转股价) * 100
        convert_value = (stock_price / convert_price) * 100
        # 溢价率 = (转债价格 - 转股价值) / 转股价值 * 100
        premium_rate = (price - convert_value) / convert_value * 100
        # 双低值 = 可转债价格 + 溢价率(百分点)
        double_low = price + premium_rate
        
        bond["溢价率"] = round(premium_rate, 2)
        bond["双低值"] = round(double_low, 2)
    else:
        # 数据不全时标记
        bond["溢价率"] = "数据不足"
        bond["双低值"] = price  # 退化为价格排序


def _filter_bonds(
    bonds: List[Dict],
    min_rating: str,
    min_volume: float,
    max_premium: float,
    exclude_st: bool
) -> List[Dict]:
    """应用筛选条件"""
    filtered = []
    min_rating_score = _rating_to_score(min_rating)
    
    for b in bonds:
        # ST排除
        if exclude_st and "ST" in b.get("名称", ""):
            continue
        
        # 评级过滤
        rating = b.get("评级", "")
        rating_score = _rating_to_score(rating)
        if rating_score >= 0 and rating_score < min_rating_score:
            continue
        
        # 成交额过滤
        vol = b.get("成交额(万)", 0)
        if isinstance(vol, (int, float)) and vol < min_volume:
            continue
        
        # 溢价率过滤
        premium = b.get("溢价率", 0)
        if isinstance(premium, (int, float)) and premium > max_premium:
            continue
        
        filtered.append(b)
    
    return filtered


# ============ 工具函数 ============

def _safe_float(val):
    """安全转float，失败返回0"""
    try:
        if val is None or val == "" or val == "-" or str(val).strip() == "":
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val):
    """安全转int，失败返回0"""
    try:
        if val is None or val == "" or val == "-" or str(val).strip() == "":
            return 0
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def _rating_to_score(rating: str) -> int:
    """
    信用评级转数值分数，越高越好。
    AAA=7, AA+=6, AA=5, AA-=4, A+=3, A=2, A-=1, BBB+=0...
    无法识别返回-1（不参与过滤）
    """
    if not rating or rating in ("", "nan", "NaN", "None", "-"):
        return -1
    rating = str(rating).strip().upper()
    mapping = {
        "AAA": 7, "AA+": 6, "AA": 5, "AA-": 4,
        "A+": 3, "A": 2, "A-": 1,
        "BBB+": 0, "BBB": -1, "BBB-": -2,
        "BB+": -3, "BB": -4, "BB-": -5,
        "B+": -6, "B": -7, "B-": -8,
        "CCC": -9, "CC": -10, "C": -11, "D": -12,
    }
    return mapping.get(rating, -1)


def get_config() -> Dict:
    """获取当前配置（用于调试）"""
    return {
        "data_sources": {
            "tencent": TENCENT_URL,
            "sina": SINA_URL,
        },
        "timeouts": {
            "primary": TIMEOUT_PRIMARY,
            "secondary": TIMEOUT_SECONDARY,
        },
        "batch_sizes": {
            "realtime": BATCH_SIZE_REALTIME,
            "bond": BATCH_SIZE_BOND,
        },
        "filters": {
            "min_rating": "AA-",
            "min_volume_wan": FILTER_MIN_VOLUME_WAN,
            "max_premium_rate": FILTER_MAX_PREMIUM_RATE,
        },
        "default_indices": DEFAULT_INDICES,
    }


# ============ 快捷入口 ============

if __name__ == "__main__":
    print("=== 棱镜行情数据配置 ===")
    print(json.dumps(get_config(), indent=2, ensure_ascii=False))
    
    print("\n=== 茅台实时行情 ===")
    result = get_realtime("sh600519")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    print("\n=== 核心指数 ===")
    for idx in get_index():
        print(f"{idx['名称']}: {idx['现价']} ({idx['涨跌幅']}%)")
    
    print("\n=== 历史K线（茅台日K最近10条）===")
    kline = get_kline("sh600519", period="daily", count=10)
    if "error" not in kline:
        for bar in kline.get("数据", []):
            print(f"{bar['日期']}: 开{bar['开盘']} 收{bar['收盘']} 高{bar['最高']} 低{bar['最低']}")
    
    print("\n=== 可转债双低TOP10 ===")
    bonds = get_bond_double_low(top_n=10)
    for b in bonds:
        if "error" in b:
            print(f"ERROR: {b['error']}")
        else:
            print(f"{b['名称']}({b['代码']}): 价格={b['价格']}, 溢价率={b.get('溢价率','?')}, 双低值={b.get('双低值','?')}")


def search_stock(keyword: str, limit: int = 10) -> List[Dict]:
    """
    按名称/拼音/代码搜索股票
    使用腾讯smartbox接口
    
    参数:
        keyword: 搜索关键词（中文/拼音/代码均可）
        limit: 最多返回条数，默认10
    返回:
        [{"代码": str, "名称": str, "市场": str, "拼音": str, "类型": str}, ...]
    """
    try:
        url = f"https://smartbox.gtimg.cn/s3/?q={keyword}&t=all"
        resp = requests.get(url, timeout=TIMEOUT_PRIMARY)
        if resp.status_code != 200 or not resp.text.strip():
            return []
        
        # 腾讯smartbox返回GBK编码，需要正确解码
        text = resp.text
        # 尝试处理Unicode转义
        if '\\u' in text:
            text = text.encode('utf-8').decode('unicode_escape')
        
        results = []
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or 'v_hint="' not in line:
                continue
            # 格式: v_hint="sh~600519~贵州茅台~gzmt~GP-A"
            try:
                content = line.split('"')[1]
                parts = content.split("~")
                if len(parts) >= 5:
                    market = parts[0]  # sh/sz/hk/us
                    code = parts[1]
                    name = parts[2]
                    pinyin = parts[3]
                    stock_type = parts[4]
                    
                    type_map = {
                        "GP-A": "A股",
                        "GP-B": "B股",
                        "IN": "指数",
                        "HK": "港股",
                        "US": "美股",
                        "FD": "基金",
                    }
                    
                    results.append({
                        "代码": f"{market}{code}",
                        "名称": name,
                        "市场": market.upper(),
                        "拼音": pinyin,
                        "类型": type_map.get(stock_type, stock_type),
                    })
            except (IndexError, ValueError):
                continue
        
        return results[:limit]
    
    except Exception as e:
        logger.error(f"搜索股票失败: {keyword} - {e}")
        return []
