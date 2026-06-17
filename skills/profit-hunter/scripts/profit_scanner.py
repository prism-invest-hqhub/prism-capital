#!/usr/bin/env python3
"""
利润猎犬数据扫描器 v1.0
自动抓取多赛道利润数据，为每日猎犬日报提供数据锚点
替代AI临时搜索，确保数据一致性和可追溯性

数据源优先级：
1. 棱镜自有API（localhost:8900）— 可转债双低、指数行情
2. 腾讯/新浪公开接口 — 实时行情备用
3. 东方财富公开接口 — ETF/新股新债

用法：
  python3 profit_scanner.py           # 全赛道扫描，输出JSON
  python3 profit_scanner.py --report  # 输出Markdown报告
  python3 profit_scanner.py --json    # 输出JSON（默认）
"""

import json
import logging
from datetime import datetime
from typing import Dict, List

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('profit-scanner')

PRISM_API = "http://127.0.0.1:8900"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


class ProfitScanner:
    """利润猎犬数据扫描器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.results = {
            "scan_time": self.scan_time,
            "convertible_bonds": [],
            "index_status": {},
            "ipo_bond": [],
            "errors": []
        }

    # ========== 赛道1：可转债扫描 ==========

    def scan_convertible_bonds(self) -> List[Dict]:
        """从棱镜自有API获取可转债双低排名"""
        logger.info("📊 扫描可转债双低排名...")

        try:
            resp = self.session.get(f"{PRISM_API}/bond/double-low", timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data:
                    bonds = []
                    for item in data:
                        name = item.get("名称", "")
                        rating = item.get("评级", "")
                        # 用户筛选标准
                        if "ST" in name:
                            continue
                        rating_ok = rating in ["AAA", "AA+", "AA", "AA-"]
                        
                        bond = {
                            "code": item.get("代码", ""),
                            "name": name,
                            "price": item.get("价格", 0),
                            "change_pct": item.get("涨跌幅", 0),
                            "volume_wan": item.get("成交额(万)", 0),
                            "turnover": item.get("换手率", 0),
                            "rating": rating,
                            "stock_code": item.get("正股代码", ""),
                            "stock_name": item.get("正股名称", ""),
                            "stock_price": item.get("正股价格", 0),
                            "premium_rate": item.get("溢价率", "N/A"),
                            "dual_low": item.get("双低值", "N/A"),
                            "rating_ok": rating_ok,
                        }
                        bonds.append(bond)

                    self.results["convertible_bonds"] = bonds
                    logger.info(f"  ✅ 获取到 {len(bonds)} 只可转债")
                    return bonds

        except Exception as e:
            logger.warning(f"  ⚠️ 棱镜API可转债获取失败: {e}")
            self.results["errors"].append(f"prism_bond: {str(e)}")

        return []

    # ========== 市场温度计 ==========

    def scan_market_status(self) -> Dict:
        """从棱镜自有API获取主要指数状态"""
        logger.info("🌡️ 扫描市场温度...")

        codes = "sh000001,sz399001,sz399006"

        try:
            resp = self.session.get(
                f"{PRISM_API}/realtime?codes={codes}", timeout=15
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    code = item.get("代码", "")
                    # 添加sh/sz前缀
                    prefix = "sh" if code == "000001" else "sz"
                    full_code = f"{prefix}{code}"
                    self.results["index_status"][full_code] = {
                        "name": item.get("名称", ""),
                        "price": item.get("现价", 0),
                        "change_pct": item.get("涨跌幅", 0),
                        "pe": item.get("市盈率", 0),
                        "volume": item.get("成交量", 0),
                        "amount": item.get("成交额", 0),
                    }

                logger.info(f"  ✅ 获取到 {len(self.results['index_status'])} 个指数")
                return self.results["index_status"]

        except Exception as e:
            logger.warning(f"  ⚠️ 棱镜API指数获取失败: {e}")
            self.results["errors"].append(f"prism_index: {str(e)}")

        # 备用：腾讯行情
        try:
            resp = self.session.get(f"{TENCENT_QUOTE_URL}{codes}", timeout=10)
            if resp.status_code == 200:
                for line in resp.text.strip().split(";"):
                    if '="' not in line:
                        continue
                    parts = line.split('~')
                    if len(parts) > 35:
                        code = parts[2] if len(parts) > 2 else ""
                        prefix = "sh" if code.endswith("000001") else "sz"
                        self.results["index_status"][f"{prefix}{code}"] = {
                            "name": parts[1] if len(parts) > 1 else "",
                            "price": float(parts[3]) if parts[3] else 0,
                            "change_pct": float(parts[32]) if parts[32] and parts[32] != '-' else 0,
                        }
        except Exception as e:
            logger.warning(f"  ⚠️ 腾讯行情备用源也失败: {e}")
            self.results["errors"].append(f"tencent_index: {str(e)}")

        return self.results["index_status"]

    # ========== 全赛道扫描 ==========

    def scan_all(self) -> Dict:
        """执行全赛道扫描"""
        logger.info(f"🐕 利润猎犬全赛道扫描开始 — {self.scan_time}")
        logger.info("=" * 50)

        self.scan_market_status()
        self.scan_convertible_bonds()

        logger.info("=" * 50)
        summary = (f"可转债:{len(self.results['convertible_bonds'])} "
                   f"指数:{len(self.results['index_status'])}")
        logger.info(f"🐕 扫描完成 — {summary}")

        if self.results["errors"]:
            logger.warning(f"⚠️ 错误: {self.results['errors']}")

        return self.results

    def to_report_md(self) -> str:
        """将扫描结果转为Markdown格式供猎犬日报使用"""
        lines = [
            f"# 🐕 利润猎犬数据扫描 — {self.scan_time}",
            "",
            "## 市场温度",
            "",
        ]

        for code, info in self.results["index_status"].items():
            change = info.get("change_pct", 0)
            emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
            pe = info.get("pe", "")
            pe_str = f" PE:{pe}" if pe else ""
            lines.append(f"- **{info['name']}**: {info.get('price', 'N/A')} {emoji}{change:+.2f}%{pe_str}")

        lines.extend(["", "## 可转债双低排名", ""])

        bonds = self.results["convertible_bonds"]
        if bonds:
            lines.append("| # | 代码 | 名称 | 价格 | 涨跌% | 溢价率 | 双低 | 评级 | 成交额 |")
            lines.append("|---|------|------|------|-------|--------|------|------|--------|")
            for i, b in enumerate(bonds, 1):
                rating_mark = "✅" if b["rating_ok"] else "⚠️"
                lines.append(
                    f"| {i} | {b['code']} | {b['name']} | {b['price']:.3f} | "
                    f"{b['change_pct']:+.2f}% | {b['premium_rate']} | {b['dual_low']} | "
                    f"{rating_mark}{b['rating']} | {b['volume_wan']:.0f}万 |"
                )

            # 筛选符合用户标准的
            qualified = [b for b in bonds if b["rating_ok"] and b["volume_wan"] >= 500]
            lines.extend(["", f"### 符合筛选标准（评级≥AA- + 成交额≥500万）: {len(qualified)} 只", ""])
            for b in qualified[:10]:
                lines.append(f"- {b['name']}({b['code']}) 价格:{b['price']:.3f} 溢价:{b['premium_rate']} 双低:{b['dual_low']} 评级:{b['rating']}")
        else:
            lines.append("*今日无数据*")

        if self.results["errors"]:
            lines.extend(["", "## ⚠️ 数据获取异常", ""])
            for err in self.results["errors"]:
                lines.append(f"- {err}")

        return "\n".join(lines)


if __name__ == "__main__":
    import sys

    scanner = ProfitScanner()

    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        scanner.scan_all()
        print(scanner.to_report_md())
    else:
        result = scanner.scan_all()
        print(json.dumps(result, ensure_ascii=False, indent=2))
