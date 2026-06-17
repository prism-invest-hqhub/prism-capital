#!/usr/bin/env python3
"""
球星卡EV计算器 v1.0
自动从eBay/130point获取卡价数据，辅助选瓜师EV计算

数据源：
1. eBay completed listings API（需要OAuth，沙箱受限）
2. 130point.com 价格追踪（爬虫，沙箱受限）
3. 腾讯/阿里拍卖国内参考

当前限制：沙箱环境外部网络受限，脚本主要提供框架
实际数据获取需在云电脑环境运行或由AI联网搜索补齐

用法：
  python3 card_ev_calc.py --product "2024 FIFA Prizm Hobby"  # 查产品EV
  python3 card_ev_calc.py --player "Messi"                    # 查球员卡价
"""

import json
import logging
from datetime import datetime
from typing import Dict, List

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('card-ev-calc')


class CardEVCalculator:
    """球星卡EV计算器"""

    # 常见产品配置参考（手动维护，需定期更新）
    PRODUCT_CONFIGS = {
        "2024-25 FIFA Prizm Hobby": {
            "price_usd": 350,
            "packs_per_box": 12,
            "cards_per_pack": 8,
            "hits_per_box": 2,  # Color Blast / Auto / Patch
            "base_rate": 0.80,  # 80%概率出Base
            "prizm_rate": 0.15,  # 15%Prizm平行
            "insert_rate": 0.04,  # 4%Insert
            "auto_rate": 0.01,   # 1%签字
        },
        "2024-25 FIFA Prizm Choice": {
            "price_usd": 120,
            "packs_per_box": 6,
            "cards_per_pack": 5,
            "hits_per_box": 1,
            "base_rate": 0.85,
            "prizm_rate": 0.10,
            "insert_rate": 0.04,
            "auto_rate": 0.01,
        },
        "2024-25 Panini Select Hobby": {
            "price_usd": 250,
            "packs_per_box": 5,
            "cards_per_pack": 5,
            "hits_per_box": 2,
            "base_rate": 0.75,
            "prizm_rate": 0.15,
            "insert_rate": 0.08,
            "auto_rate": 0.02,
        },
    }

    # 平台费率
    EBAY_FEE_RATE = 0.13   # eBay成交费
    PAYMENT_FEE_RATE = 0.03  # 支付处理费
    VOLATILITY_DISCOUNT = 0.7  # 波动性折扣
    LIQUIDITY_DISCOUNT = 0.8   # 流动性折扣

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def calculate_ev(self, product_name: str, hit_prices: Dict[str, float] = None) -> Dict:
        """
        计算产品EV
        hit_prices: {hit_type: median_price_usd}，需从eBay/130point获取
        """
        config = self.PRODUCT_CONFIGS.get(product_name)
        if not config:
            return {"error": f"产品 '{product_name}' 未在配置中，请手动提供参数"}

        box_price = config["price_usd"]
        
        if hit_prices:
            # 有实际价格数据时做精确EV
            total_ev = 0
            for hit_type, price in hit_prices.items():
                # 中位数价格 × 概率
                rate = config.get(f"{hit_type}_rate", 0.01)
                total_ev += rate * price

            # 扣除费用
            net_ev = total_ev * self.VOLATILITY_DISCOUNT * self.LIQUIDITY_DISCOUNT
            net_ev -= (net_ev * (self.EBAY_FEE_RATE + self.PAYMENT_FEE_RATE))

            rEV = net_ev - box_price
            ev_pct = (rEV / box_price) * 100 if box_price > 0 else 0

            if rEV > box_price * 0.2:
                verdict = "🟢 甜瓜"
            elif rEV > 0:
                verdict = "🟡 生瓜"
            else:
                verdict = "🔴 坏瓜"

            return {
                "product": product_name,
                "box_price_usd": box_price,
                "raw_ev_usd": total_ev,
                "risk_adjusted_ev_usd": net_ev,
                "rEV_usd": rEV,
                "ev_pct": ev_pct,
                "verdict": verdict,
                "hit_prices": hit_prices,
                "disclaimers": [
                    "EV基于中位数价格，实际波动可能很大",
                    "未扣除时间成本和运费",
                    "市场价每日变化，结果仅供参考",
                ]
            }
        else:
            # 无价格数据，仅输出框架
            return {
                "product": product_name,
                "box_price_usd": box_price,
                "config": config,
                "message": "⚠️ 缺少Hit价格数据，无法计算精确EV。请提供eBay/130point中位数价格。",
                "required_data": {
                    "base_median_usd": "Base卡中位数价格",
                    "prizm_median_usd": "Prizm平行中位数价格",
                    "insert_median_usd": "Insert中位数价格",
                    "auto_median_usd": "签字卡中位数价格",
                },
                "formula": "EV = Σ(概率 × 中位数) × 波动折扣(0.7) × 流动折扣(0.8) - 平台费(16%) - 盒价",
            }

    def list_products(self) -> List[str]:
        """列出已配置的产品"""
        return list(self.PRODUCT_CONFIGS.keys())

    def add_product(self, name: str, config: Dict):
        """添加新产品配置"""
        self.PRODUCT_CONFIGS[name] = config


if __name__ == "__main__":
    import sys

    calc = CardEVCalculator()

    if len(sys.argv) > 2 and sys.argv[1] == "--product":
        product = sys.argv[2]
        result = calc.calculate_ev(product)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 2 and sys.argv[1] == "--ev":
        # 格式: --ev "产品名" --prices "base:5,prizm:20,insert:50,auto:200"
        product = sys.argv[2]
        prices = {}
        if len(sys.argv) > 4 and sys.argv[3] == "--prices":
            for pair in sys.argv[4].split(","):
                k, v = pair.split(":")
                prices[k.strip()] = float(v.strip())
        result = calc.calculate_ev(product, prices if prices else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 默认列出产品
        print("🍉 球星卡选瓜师 EV计算器")
        print(f"\n已配置产品 ({len(calc.list_products())}):")
        for p in calc.list_products():
            cfg = calc.PRODUCT_CONFIGS[p]
            print(f"  - {p} (${cfg['price_usd']})")
        print("\n用法:")
        print('  python3 card_ev_calc.py --product "2024-25 FIFA Prizm Hobby"')
        print('  python3 card_ev_calc.py --ev "2024-25 FIFA Prizm Hobby" --prices "base:3,prizm:15,insert:40,auto:180"')
