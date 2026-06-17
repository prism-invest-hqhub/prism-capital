#!/usr/bin/env python3
"""
棱镜先知量化信号模块 v1.0
为预测提供数据锚点，而非纯AI推理
获取关键市场指标用于8模型分析

数据源：
1. 棱镜自有API — 指数行情、PE
2. 腾讯/新浪 — 实时行情备用

用法：
  python3 oracle_signals.py           # 输出JSON信号
  python3 oracle_signals.py --report  # 输出Markdown信号报告
"""

import json
import logging
from datetime import datetime
from typing import Dict

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('oracle-signals')

PRISM_API = "http://127.0.0.1:8900"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


class OracleSignals:
    """棱镜先知量化信号采集器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.signals = {
            "scan_time": self.scan_time,
            "indices": {},
            "market_temperature": "N/A",
            "pe_percentile_hint": "N/A",
            "errors": []
        }

    def _interpret_temperature(self, change_pct: float, pe: float) -> str:
        """
        简易市场温度判断（基于PE和涨跌幅）
        精确恐贪指数需要更多数据源，这里提供方向性判断
        """
        if pe > 60:
            return "🔥过热（PE极高，马克斯周期：狂热期）"
        elif pe > 40:
            return "🟡偏热（PE较高，需警惕）"
        elif pe > 20:
            return "🟢温和（PE正常，安全边际尚可）"
        elif pe > 10:
            return "🔵偏冷（PE较低，可能是机会）"
        else:
            return "🧊极冷（PE很低，格雷厄姆式机会）"

    def scan_indices(self) -> Dict:
        """获取主要指数+PE，用于周期定位和安全边际判断"""
        logger.info("🔮 采集量化信号...")

        # 主要指数
        codes = "sh000001,sz399001,sz399006"
        
        # 宽基ETF作为市场代理
        etf_codes = "sh510310,sh510300,sh510500"  # 沪深300ETF等

        try:
            # 指数行情
            resp = self.session.get(
                f"{PRISM_API}/realtime?codes={codes}", timeout=15
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    code = item.get("代码", "")
                    prefix = "sh" if code == "000001" else "sz"
                    full_code = f"{prefix}{code}"
                    pe = item.get("市盈率", 0) or 0
                    self.signals["indices"][full_code] = {
                        "name": item.get("名称", ""),
                        "price": item.get("现价", 0),
                        "change_pct": item.get("涨跌幅", 0),
                        "pe": pe,
                        "total_mv": item.get("总市值", 0),
                        "temperature": self._interpret_temperature(item.get("涨跌幅", 0), pe),
                    }

        except Exception as e:
            logger.warning(f"  ⚠️ 指数信号获取失败: {e}")
            self.signals["errors"].append(f"prism_index: {str(e)}")

        # 综合市场温度（基于上证指数PE）
        sh_data = self.signals["indices"].get("sh000001", {})
        if sh_data:
            pe = sh_data.get("pe", 0)
            self.signals["market_temperature"] = self._interpret_temperature(
                sh_data.get("change_pct", 0), pe
            )
            # PE历史分位方向性判断（精确需历史数据）
            if pe > 20:
                self.signals["pe_percentile_hint"] = f"PE={pe:.1f} 偏高（>70%分位可能性大）→ 格雷厄姆：安全边际不足"
            elif pe > 15:
                self.signals["pe_percentile_hint"] = f"PE={pe:.1f} 中性（40-70%分位）→ 格雷厄姆：有边际但不大"
            else:
                self.signals["pe_percentile_hint"] = f"PE={pe:.1f} 偏低（<40%分位可能性大）→ 格雷厄姆：安全边际充足"

        logger.info(f"  ✅ 采集到 {len(self.signals['indices'])} 个指数信号")
        return self.signals

    def scan_all(self) -> Dict:
        """执行全量信号采集"""
        logger.info(f"🔮 棱镜先知信号采集 — {self.scan_time}")
        self.scan_indices()
        return self.signals

    def to_report_md(self) -> str:
        """转为Markdown格式供先知预测使用"""
        lines = [
            f"# 🔮 棱镜先知量化信号 — {self.scan_time}",
            "",
            "## 市场温度",
            "",
            f"**综合判断**: {self.signals['market_temperature']}",
            "",
            f"**PE分位提示**: {self.signals['pe_percentile_hint']}",
            "",
            "## 指数信号",
            "",
        ]

        for code, info in self.signals["indices"].items():
            change = info.get("change_pct", 0)
            emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
            lines.append(
                f"- **{info['name']}**: {info.get('price', 'N/A')} "
                f"{emoji}{change:+.2f}% PE:{info.get('pe', 'N/A')} "
                f"— {info.get('temperature', '')}"
            )

        lines.extend(["", "## 模型锚点建议", ""])
        lines.append("- **格雷厄姆（安全边际）**: " + self.signals['pe_percentile_hint'])
        lines.append(f"- **马克斯（周期定位）**: {self.signals['market_temperature']}")
        lines.append("- **索罗斯（反身性）**: 需结合资金流向和舆情判断反身性阶段")
        lines.append("- **西蒙斯（量化信号）**: PE和涨跌幅是基础信号，需更多技术指标确认")
        lines.append("- **芒格（多元格栅）**: 当前PE水平在不同学科视角下意味着什么？")

        if self.signals["errors"]:
            lines.extend(["", "## ⚠️ 信号获取异常", ""])
            for err in self.signals["errors"]:
                lines.append(f"- {err}")

        return "\n".join(lines)


if __name__ == "__main__":
    import sys

    scanner = OracleSignals()

    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        scanner.scan_all()
        print(scanner.to_report_md())
    else:
        result = scanner.scan_all()
        print(json.dumps(result, ensure_ascii=False, indent=2))
