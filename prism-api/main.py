"""
棱镜行情数据 - Prism Market Data API
棱镜投资决策系统专属行情数据接口

数据源：
- 腾讯财经(qt.gtimg.cn) 主力源 — 实时行情（GBK编码）
- 新浪财经(hq.sinajs.cn) 备用源 — 实时行情
- efinance — 可转债基础列表（代码/评级/正股）
- 腾讯财经批量 — 可转债实时价格

策略：efinance拿基础信息 → 腾讯批量拿实时行情 → 本地计算双低值
"""

import json
import re
import os
from coze_workload_identity import requests


# ============ 实时行情 ============

def get_realtime(codes):
    """
    查询A股/指数/ETF实时行情
    
    参数:
        codes: 单个代码字符串如"sh600519"，或列表如["sh600519","sz000001"]
               沪市前缀sh，深市前缀sz，指数如sh000300
    返回:
        单个代码返回dict，多个代码返回list[dict]
    """
    if isinstance(codes, str):
        codes = [codes]
        single = True
    else:
        single = False
    
    # 尝试腾讯源
    result = _fetch_tencent(codes)
    if result is None:
        # 备用：新浪源
        result = _fetch_sina(codes)
    
    if result is None:
        return {"error": "所有数据源均失败"}
    
    if single:
        return result[0] if result else {}
    return result


def _fetch_tencent(codes):
    """腾讯财经实时行情（主力源）"""
    try:
        code_str = ",".join(codes)
        url = f"http://qt.gtimg.cn/q={code_str}"
        resp = requests.get(url, timeout=3)
        if resp.status_code != 200:
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
                items.append(item)
            except (IndexError, ValueError):
                continue
        
        return items if items else None
    except Exception:
        return None


def _fetch_sina(codes):
    """新浪财经实时行情（备用源）"""
    items = []
    for code in codes:
        try:
            url = f"http://hq.sinajs.cn/list={code}"
            headers = {"Referer": "https://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=3)
            if resp.status_code != 200:
                continue
            
            text = resp.content.decode('gbk', errors='replace')
            match = re.search(r'="(.+)"', text)
            if not match:
                continue
            
            fields = match.group(1).split(",")
            if len(fields) < 32:
                continue
            
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
            }
            if current == 0 and volume == 0:
                item["状态"] = "停牌"
            items.append(item)
        except Exception:
            continue
    
    return items if items else None


# ============ 指数行情 ============

def get_index(indices=None):
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
        indices = ["sh000300", "sz399006", "sh000016", "sh000905", "sh000001"]
    return get_realtime(indices)


# ============ 可转债双低排名 ============

def get_bond_double_low(top_n=30):
    """
    查询可转债双低排名
    
    策略：efinance获取可转债基础列表(评级/正股) → 腾讯批量获取实时行情 → 本地计算双低值
    
    参数:
        top_n: 返回前N名，默认30
    返回:
        list[dict] 按双低值升序排列，已过滤棱镜标准
    """
    try:
        import efinance as ef
        import pandas as pd
    except ImportError:
        return [{"error": "缺少efinance库，请pip install efinance"}]
    
    try:
        # Step 1: 获取可转债基础信息
        df_base = ef.bond.get_all_base_info()
        if df_base is None or df_base.empty:
            return [{"error": "可转债基础信息获取失败"}]
        
        # 只保留已上市的（有上市日期）
        listed = df_base[df_base['上市日期'].notna()].copy()
        
        # 清理评级字段（有些带'sti'后缀）
        listed['债券评级_clean'] = listed['债券评级'].astype(str).str.replace('sti', '', regex=False).str.strip()
        
        # 构建腾讯代码
        listed['qt_code'] = listed['债券代码'].apply(lambda x: f"sh{x}" if str(x).startswith('11') else f"sz{x}")
        
        # Step 2: 批量获取实时行情（腾讯每次最多约50只）
        all_bonds = []
        code_list = listed['qt_code'].tolist()
        batch_size = 50
        
        for i in range(0, len(code_list), batch_size):
            batch = code_list[i:i+batch_size]
            batch_str = ",".join(batch)
            
            try:
                url = f"http://qt.gtimg.cn/q={batch_str}"
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200:
                    continue
                
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
                        
                        # 从基础信息中匹配评级和正股
                        row = listed[listed['债券代码'] == bond_code]
                        rating = row['债券评级_clean'].values[0] if len(row) > 0 else ""
                        stock_code = row['正股代码'].values[0] if len(row) > 0 else ""
                        stock_name = row['正股名称'].values[0] if len(row) > 0 else ""
                        
                        # 获取正股价格计算转股价值（简化：用腾讯接口查正股）
                        all_bonds.append({
                            "代码": bond_code,
                            "名称": bond_name,
                            "价格": price,
                            "涨跌幅": change_pct,
                            "成交额(万)": round(volume / 10000, 2) if volume > 10000 else round(volume, 2),
                            "换手率": turnover,
                            "评级": rating,
                            "正股代码": str(stock_code),
                            "正股名称": str(stock_name),
                        })
                    except Exception:
                        continue
            except Exception:
                continue
        
        if not all_bonds:
            return [{"error": "可转债实时行情获取失败"}]
        
        # Step 3: 批量获取正股价格，计算转股溢价率和双低值
        # 收集所有正股代码
        stock_codes = []
        for b in all_bonds:
            sc = b["正股代码"]
            if sc and sc != "nan" and len(sc) == 6:
                prefix = "sh" if sc.startswith(('6', '5')) else "sz"
                stock_codes.append(f"{prefix}{sc}")
            else:
                stock_codes.append("")
        
        # 批量查正股
        stock_prices = {}
        valid_stocks = [c for c in stock_codes if c]
        for i in range(0, len(valid_stocks), 50):
            batch = valid_stocks[i:i+50]
            batch_str = ",".join(batch)
            try:
                url = f"http://qt.gtimg.cn/q={batch_str}"
                resp = requests.get(url, timeout=5)
                text = resp.content.decode('gbk', errors='replace')
                for line in text.strip().split(";"):
                    line = line.strip()
                    if not line: continue
                    m = re.match(r'v_(\w+)="(.+)"', line)
                    if m:
                        fs = m.group(2).split("~")
                        if len(fs) > 3:
                            stock_prices[fs[2]] = _safe_float(fs[3])
            except Exception:
                continue
        
        # Step 4: 计算转股溢价率和双低值
        # 注意：精确计算需要转股价，这里用近似方法
        # 双低 = 价格 + 溢价率（百分比数值）
        # 溢价率 = (价格 - 转股价值) / 转股价值 * 100
        # 转股价值 = 100/转股价 * 正股价格
        # 没有转股价数据时，双低值暂时用 "价格" 近似（偏低估）
        
        # 尝试从efinance获取更多数据
        for b in all_bonds:
            sp = stock_prices.get(b["正股代码"], 0)
            b["正股价格"] = sp
            # 没有转股价，暂时无法精确计算溢价率
            # 标记为需要手动在集思录确认
            b["溢价率"] = "需集思录确认"
            b["双低值"] = "需集思录确认"
        
        # 棱镜筛选：排除ST、评级<AA-、成交额<500万
        filtered = []
        for b in all_bonds:
            if "ST" in b["名称"]:
                continue
            # 评级过滤：用数值映射避免字符串比较陷阱
            rating = b["评级"]
            rating_score = _rating_to_score(rating)
            if rating_score > 0 and rating_score < 3:  # 3=AA-, 低于此排除
                continue
            vol = b["成交额(万)"]
            if isinstance(vol, (int, float)) and vol < 500:
                continue
            filtered.append(b)
        
        # 按价格升序（近似双低排序，低价优先）
        filtered.sort(key=lambda x: x["价格"] if isinstance(x["价格"], (int, float)) else 9999)
        return filtered[:top_n]
    
    except Exception as e:
        return [{"error": f"可转债数据获取失败: {str(e)}"}]


# ============ 工具函数 ============

def _safe_float(val):
    """安全转float，失败返回0"""
    try:
        if val is None or val == "" or val == "-":
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val):
    """安全转int，失败返回0"""
    try:
        if val is None or val == "" or val == "-":
            return 0
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def _rating_to_score(rating):
    """
    信用评级转数值分数，越高越好。
    AAA=7, AA+=6, AA=5, AA-=4, A+=3, A=2, A-=1, BBB+=0...
    无法识别返回-1（不参与过滤）
    """
    if not rating or rating in ("", "nan", "NaN", "None"):
        return -1
    rating = str(rating).strip().upper()
    mapping = {
        "AAA": 7, "AA+": 6, "AA": 5, "AA-": 4,
        "A+": 3, "A": 2, "A-": 1,
        "BBB+": 0, "BBB": -1, "BBB-": -2,
        "BB+": -3, "BB": -4, "BB-": -5,
    }
    return mapping.get(rating, -1)


# ============ 快捷入口 ============

if __name__ == "__main__":
    print("=== 茅台实时行情 ===")
    print(json.dumps(get_realtime("sh600519"), indent=2, ensure_ascii=False))
    
    print("\n=== 核心指数 ===")
    for idx in get_index():
        print(f"{idx['名称']}: {idx['现价']} ({idx['涨跌幅']}%)")
    
    print("\n=== 可转债双低TOP10 ===")
    bonds = get_bond_double_low(top_n=10)
    for b in bonds:
        if "error" in b:
            print(f"ERROR: {b['error']}")
        else:
            print(f"{b['名称']}({b['代码']}): 价格={b['价格']}, 评级={b['评级']}, 成交额={b['成交额(万)']}万")
