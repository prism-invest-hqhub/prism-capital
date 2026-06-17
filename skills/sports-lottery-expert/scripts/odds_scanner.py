#!/usr/bin/env python3
"""
体彩赔率采集器 v1.0
自动获取近期赛事赔率，为体彩购买专家提供数据锚点

数据源：竞彩网 + 500彩票 + 腾讯体育
注意：沙箱环境外部网络受限，部分源可能不可用

用法：
  python3 odds_scanner.py           # 输出JSON赔率数据
  python3 odds_scanner.py --report  # 输出Markdown赔率报告
"""

import json
import logging
from datetime import datetime
from typing import Dict, List

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('odds-scanner')


class OddsScanner:
    """体彩赔率采集器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.sporttery.cn/',
        })
        self.scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.results = {
            "scan_time": self.scan_time,
            "matches": [],
            "errors": []
        }

    def scan_sporttery(self) -> List[Dict]:
        """
        从竞彩网获取近期赛事赔率
        API: https://www.sporttery.cn/jc/jsq/matchlist.json
        """
        logger.info("⚽ 扫描竞彩赛事赔率...")

        urls_to_try = [
            "https://www.sporttery.cn/jc/jsq/matchlist.json",
            "https://i.sporttery.cn/api/fb_match_info/get_pool_list?pool=c1&sell_status=1",
        ]

        for url in urls_to_try:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    matches = []

                    # 解析竞彩数据（格式因源不同而异）
                    if isinstance(data, list):
                        for m in data[:20]:
                            matches.append({
                                "match_id": m.get("matchId", m.get("id", "")),
                                "league": m.get("league", m.get("matchComp", "")),
                                "home": m.get("homeTeam", m.get("homeTeamName", "")),
                                "away": m.get("awayTeam", m.get("awayTeamName", "")),
                                "date": m.get("matchDate", m.get("matchTime", "")),
                                "odds_win": m.get("oddsWin", m.get("spWin", "")),
                                "odds_draw": m.get("oddsDraw", m.get("spDraw", "")),
                                "odds_lose": m.get("oddsLose", m.get("spLose", "")),
                            })
                    elif isinstance(data, dict):
                        items = data.get("data", data.get("result", []))
                        if isinstance(items, list):
                            for m in items[:20]:
                                matches.append({
                                    "match_id": m.get("matchId", m.get("id", "")),
                                    "league": m.get("league", m.get("matchComp", "")),
                                    "home": m.get("homeTeam", m.get("homeTeamName", "")),
                                    "away": m.get("awayTeam", m.get("awayTeamName", "")),
                                    "date": m.get("matchDate", m.get("matchTime", "")),
                                    "odds_win": m.get("oddsWin", m.get("spWin", "")),
                                    "odds_draw": m.get("oddsDraw", m.get("spDraw", "")),
                                    "odds_lose": m.get("oddsLose", m.get("spLose", "")),
                                })

                    if matches:
                        self.results["matches"] = matches
                        logger.info(f"  ✅ 获取到 {len(matches)} 场赛事")
                        return matches

            except Exception as e:
                logger.warning(f"  ⚠️ {url} 获取失败: {e}")
                self.results["errors"].append(f"sporttery: {str(e)}")
                continue

        logger.warning("  ⚠️ 所有赔率源均不可用，AI需自行搜索")
        return []

    def scan_all(self) -> Dict:
        """执行全量赔率采集"""
        logger.info(f"⚽ 体彩赔率采集 — {self.scan_time}")
        self.scan_sporttery()
        return self.results

    def to_report_md(self) -> str:
        """转为Markdown格式"""
        lines = [
            f"# ⚽ 体彩赔率快报 — {self.scan_time}",
            "",
        ]

        if self.results["matches"]:
            lines.append("| # | 联赛 | 主队 | 客队 | 胜 | 平 | 负 |")
            lines.append("|---|------|------|------|-----|-----|-----|")
            for i, m in enumerate(self.results["matches"], 1):
                lines.append(
                    f"| {i} | {m.get('league', '')} | {m.get('home', '')} | "
                    f"{m.get('away', '')} | {m.get('odds_win', '-')} | "
                    f"{m.get('odds_draw', '-')} | {m.get('odds_lose', '-')} |"
                )
        else:
            lines.append("*赔率源不可用，请AI联网搜索获取*")

        if self.results["errors"]:
            lines.extend(["", "## ⚠️ 数据获取异常", ""])
            for err in self.results["errors"]:
                lines.append(f"- {err}")

        lines.extend(["", "---", "> ⚠️ 体彩竞彩返奖率约70-75%，长期投注数学期望为负。仅限娱乐，≤100元。"])

        return "\n".join(lines)


if __name__ == "__main__":
    import sys

    scanner = OddsScanner()

    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        scanner.scan_all()
        print(scanner.to_report_md())
    else:
        result = scanner.scan_all()
        print(json.dumps(result, ensure_ascii=False, indent=2))
