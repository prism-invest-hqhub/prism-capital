"""
棱镜自我进化引擎 — Prism Evolution Engine v1.1
L4(可量化) → L5(自适应) 的核心基础设施

五大能力：
1. 决策日志 — 每次决策全链路记录（推理/记忆/模型/费用）
2. 结果追踪 — 标记建议后的实际结果，自动对比
3. 自我学习 — 从反馈中提取教训，自动修改记忆和规则
4. 自动决策闭环 — 可转债筛选/ETF分析自动记录结果
5. 策略回测 — 基于历史决策验证策略有效性

这就是L5的"大脑皮层"——不靠人喂，自己从经验中进化。
"""

import sqlite3
import json
import time
import os
from datetime import datetime
from typing import Optional, List, Dict, Tuple

JOURNAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal", "evolution.db")


class DecisionJournal:
    """
    决策日志 — L4基础
    
    记录每次决策的完整链路：
    - 输入：用户问题/市场状态
    - 推理：召回的记忆、使用的模型、推理过程
    - 输出：给出的建议/结论
    - 元数据：费用、耗时、置信度
    """
    
    def __init__(self, db_path: str = JOURNAL_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                decision_type TEXT NOT NULL,
                input_text TEXT,
                memories_recalled TEXT,
                model_used TEXT,
                output_text TEXT,
                confidence REAL DEFAULT 0.5,
                cost_yuan REAL DEFAULT 0,
                elapsed_seconds REAL DEFAULT 0,
                result_actual TEXT,
                result_timestamp REAL,
                result_accuracy REAL,
                feedback TEXT,
                lesson_learned TEXT,
                rule_modified TEXT,
                auto_evolved INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_type ON decisions(decision_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_time ON decisions(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_result ON decisions(result_accuracy)")
        conn.commit()
        conn.close()
    
    def record(self, decision_type: str, input_text: str, output_text: str,
               memories_recalled: List[Dict] = None, model_used: str = "",
               confidence: float = 0.5, cost_yuan: float = 0,
               elapsed_seconds: float = 0, metadata: dict = None) -> int:
        """记录一次决策"""
        now = time.time()
        mem_str = json.dumps(memories_recalled or [], ensure_ascii=False)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO decisions (timestamp, decision_type, input_text, memories_recalled,
                                  model_used, output_text, confidence, cost_yuan,
                                  elapsed_seconds, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (now, decision_type, input_text, mem_str, model_used, output_text,
              confidence, cost_yuan, elapsed_seconds, json.dumps(metadata or {})))
        did = c.lastrowid
        conn.commit()
        conn.close()
        return did
    
    def add_result(self, decision_id: int, actual_result: str, accuracy: float = None):
        """补充决策的实际结果"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            UPDATE decisions SET result_actual = ?, result_timestamp = ?, result_accuracy = ?
            WHERE id = ?
        """, (actual_result, time.time(), accuracy, decision_id))
        conn.commit()
        conn.close()
    
    def add_feedback(self, decision_id: int, feedback: str):
        """用户反馈"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE decisions SET feedback = ? WHERE id = ?", (feedback, decision_id))
        conn.commit()
        conn.close()
    
    def add_lesson(self, decision_id: int, lesson: str, rule_modified: str = ""):
        """记录从这次决策中学到的教训"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE decisions SET lesson_learned = ?, rule_modified = ?, auto_evolved = 1 WHERE id = ?",
                  (lesson, rule_modified, decision_id))
        conn.commit()
        conn.close()
    
    def get_unresolved(self, limit: int = 20) -> List[Dict]:
        """获取还没有结果追踪的决策（用于自动追踪）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, decision_type, input_text, output_text, confidence
            FROM decisions WHERE result_actual IS NULL AND auto_evolved = 0
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()
        return [dict(zip(["id","timestamp","decision_type","input_text","output_text","confidence"], r)) 
                for r in rows]
    
    def accuracy_stats(self, decision_type: str = None) -> Dict:
        """准确率统计"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if decision_type:
            c.execute("SELECT AVG(result_accuracy), COUNT(*) FROM decisions WHERE result_accuracy IS NOT NULL AND decision_type = ?", (decision_type,))
        else:
            c.execute("SELECT AVG(result_accuracy), COUNT(*) FROM decisions WHERE result_accuracy IS NOT NULL")
        avg_acc, count = c.fetchone()
        c.execute("SELECT COUNT(*) FROM decisions WHERE feedback IS NOT NULL")
        feedback_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM decisions WHERE lesson_learned IS NOT NULL")
        lessons_count = c.fetchone()[0]
        conn.close()
        return {
            "total_decisions": count or 0,
            "avg_accuracy": round(avg_acc, 3) if avg_acc else None,
            "with_feedback": feedback_count,
            "with_lessons": lessons_count,
        }
    
    def recent(self, limit: int = 10) -> List[Dict]:
        """最近决策"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, decision_type, input_text, output_text, 
                   confidence, result_accuracy, feedback, lesson_learned
            FROM decisions ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()
        keys = ["id","timestamp","decision_type","input_text","output_text",
                "confidence","result_accuracy","feedback","lesson_learned"]
        return [dict(zip(keys, r)) for r in rows]


class SelfEvolver:
    """
    自我进化器 — L5核心
    
    从决策结果中自动学习：
    1. 扫描有结果但没学教训的决策
    2. 分析：预测对了还是错了
    3. 提取教训 → 写入记忆
    4. 如果同类错误反复出现 → 自动调整规则权重
    """
    
    def __init__(self, journal: DecisionJournal, memory=None):
        self.journal = journal
        self.memory = memory  # PrismMemory实例
    
    def evolve(self) -> List[Dict]:
        """执行一轮自我进化，返回学到的教训列表"""
        lessons = []
        
        # 扫描有反馈但没提取教训的决策
        conn = sqlite3.connect(self.journal.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, decision_type, input_text, output_text, 
                   confidence, result_actual, result_accuracy, feedback
            FROM decisions 
            WHERE feedback IS NOT NULL AND lesson_learned IS NULL
        """)
        rows = c.fetchall()
        conn.close()
        
        for row in rows:
            did, dtype, inp, out, conf, actual, accuracy, feedback = row
            lesson = self._extract_lesson(dtype, out, actual, accuracy, feedback)
            if lesson:
                # 记录教训
                self.journal.add_lesson(did, lesson["text"], lesson.get("rule_change", ""))
                # 写入记忆
                if self.memory:
                    self.memory.add(
                        content=lesson["text"],
                        tag="lesson",
                        trigger_condition=lesson.get("trigger", dtype),
                        decision_weight=lesson.get("weight", "strong"),
                        expiry_condition="never",
                        source="self_evolution"
                    )
                lessons.append({"decision_id": did, **lesson})
        
        return lessons
    
    def _extract_lesson(self, decision_type: str, output: str, 
                        actual: str, accuracy: float, feedback: str) -> Optional[Dict]:
        """从反馈中提取结构化教训"""
        feedback_lower = (feedback or "").lower()
        
        # 用户负面反馈
        if any(w in feedback_lower for w in ["错", "不对", "不准", "扯", "瞎", "不行", "差", "bad", "wrong"]):
            return {
                "text": f"决策失误：{output[:80]}→实际{actual or '用户否定'}，原因：{feedback[:60]}",
                "trigger": decision_type,
                "weight": "strong",
                "rule_change": f"降低此类{decision_type}建议的置信度",
            }
        
        # 用户正面反馈
        if any(w in feedback_lower for w in ["对", "准", "好", "靠谱", "牛", "good", "right", "nice"]):
            return {
                "text": f"决策正确：{output[:80]}，用户确认：{feedback[:40]}",
                "trigger": decision_type,
                "weight": "reference",
                "rule_change": "",
            }
        
        # 量化准确率
        if accuracy is not None:
            if accuracy < 0.3:
                return {
                    "text": f"预测偏差大(准确率{accuracy:.0%})：{output[:60]}",
                    "trigger": decision_type,
                    "weight": "strong",
                    "rule_change": f"{decision_type}类预测需更保守",
                }
            elif accuracy > 0.7:
                return {
                    "text": f"预测准确(准确率{accuracy:.0%})：{output[:60]}",
                    "trigger": decision_type,
                    "weight": "reference",
                    "rule_change": "",
                }
        
        return None
    
    def auto_tune(self) -> Dict:
        """
        自动调参 — L5核心能力
        
        统计各类决策的准确率，自动调整：
        - 准确率<40%的决策类型 → 提高保守度
        - 准确率>70%的决策类型 → 可以更积极
        - 反复出错的规则 → 升级为hard rule
        """
        conn = sqlite3.connect(self.journal.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT decision_type, 
                   COUNT(*) as total,
                   AVG(result_accuracy) as avg_accuracy,
                   SUM(CASE WHEN feedback LIKE '%错%' OR feedback LIKE '%不对%' THEN 1 ELSE 0 END) as neg_count
            FROM decisions 
            WHERE result_accuracy IS NOT NULL OR feedback IS NOT NULL
            GROUP BY decision_type
        """)
        rows = c.fetchall()
        conn.close()
        
        adjustments = []
        for row in rows:
            dtype, total, avg_acc, neg_count = row
            if total < 3:
                continue  # 样本太少不调
            
            if avg_acc is not None and avg_acc < 0.4:
                adjustments.append({
                    "type": dtype, "action": "raise_caution",
                    "reason": f"准确率{avg_acc:.0%}偏低({total}次)", 
                    "suggestion": "提高置信度阈值，输出更保守"
                })
            elif avg_acc is not None and avg_acc > 0.7:
                adjustments.append({
                    "type": dtype, "action": "allow_aggressive",
                    "reason": f"准确率{avg_acc:.0%}良好({total}次)",
                    "suggestion": "可适当提高建议力度"
                })
            
            if neg_count and neg_count >= 3:
                adjustments.append({
                    "type": dtype, "action": "escalate_rule",
                    "reason": f"负面反馈{neg_count}次",
                    "suggestion": f"考虑将{dtype}相关软规则升级为硬规则"
                })
        
        return {"adjustments": adjustments, "types_analyzed": len(rows)}


class MultiAgentCoordinator:
    """
    多Agent协调器 — L5的"多Agent协同进化"
    
    棱镜不是一个人在战斗，而是调度多个专职Agent：
    - risk_agent: 7×24监控风险，触发红线自动预警
    - market_agent: 行情数据追踪，异动即时报告
    - content_agent: 内容创作，定时产出
    - research_agent: 深度研究，按需启动
    
    当前实现：通过扣子的session_spawn + calendar调度
    未来实现：自建Agent间通信（通过Brain API的WebSocket）
    """
    
    AGENT_REGISTRY = {
        "risk": {"role": "风控Agent", "trigger": "市场异动/止损触发", "schedule": "实时"},
        "market": {"role": "行情Agent", "trigger": "定时+异动", "schedule": "每日20:00"},
        "content": {"role": "内容Agent", "trigger": "定时发布", "schedule": "每日"},
        "research": {"role": "研究Agent", "trigger": "用户提问/新标的", "schedule": "按需"},
    }
    
    def status(self) -> Dict:
        return {
            "coordinator": "棱镜",
            "agents": self.AGENT_REGISTRY,
            "communication": "session_spawn + calendar + websocket",
            "evolution_level": "L2→L3",
            "next_upgrade": "Agent间共享决策日志，协同学习",
        }


if __name__ == "__main__":
    journal = DecisionJournal()
    evolver = SelfEvolver(journal)
    coordinator = MultiAgentCoordinator()
    
    # 测试：记录一次决策
    did = journal.record(
        decision_type="buy",
        input_text="三花转债现价108，双低115，是否买入？",
        output_text="建议观望，等待7-8月窗口，当前全市场高估",
        confidence=0.7,
        model_used="deepseek-v3"
    )
    print(f"决策已记录 ID={did}")
    
    # 模拟结果追踪
    journal.add_result(did, "三花转债涨至112(+3.7%)", accuracy=0.3)
    journal.add_feedback(did, "说观望结果涨了，偏保守")
    
    # 执行自我进化
    lessons = evolver.evolve()
    print(f"\n学到教训: {len(lessons)}")
    for l in lessons:
        print(f"  📝 {l['text'][:80]}")
    
    # 自动调参
    tune = evolver.auto_tune()
    print(f"\n调参建议: {len(tune['adjustments'])}")
    for a in tune['adjustments']:
        print(f"  🔧 {a['type']}: {a['suggestion']}")
    
    # 多Agent状态
    print(f"\n{json.dumps(coordinator.status(), ensure_ascii=False, indent=2)}")


class AutoDecisionLoop:
    """
    自动决策闭环 — L4→L5的核心
    
    自动追踪投资决策结果：
    1. 可转债筛选：每天自动记录筛选结果，连续无标的=防守正确
    2. ETF技术分析：追踪信号出现后的实际走势
    3. 策略验证：回测历史决策准确率
    """
    
    def __init__(self, journal: DecisionJournal):
        self.journal = journal
    
    def record_bond_screening(self, result: Dict):
        """记录可转债筛选结果，自动判定防守正确性"""
        total = result.get("total", 0)
        passed = result.get("passed", 0)
        min_double_low = result.get("min_double_low", 999)
        
        if passed == 0:
            conclusion = f"防守正确：全市场{total}只可转债，双低最低{min_double_low}，无符合标准标的"
            accuracy = 0.9
        else:
            conclusion = f"发现{passed}只符合标准标的，双低最低{min_double_low}"
            accuracy = None
        
        did = self.journal.record(
            decision_type="bond_screening_auto",
            input_text=f"可转债自动筛选：{total}只扫描，{passed}只通过",
            output_text=conclusion,
            confidence=0.85 if passed == 0 else 0.6,
            model_used="prism-auto-screen",
            metadata={"total": total, "passed": passed, "min_dl": min_double_low,
                      "date": datetime.now().strftime("%Y-%m-%d")}
        )
        
        if accuracy:
            self.journal.add_result(did, conclusion, accuracy)
        
        return did
    
    def record_etf_analysis(self, code: str, analysis: Dict):
        """记录ETF技术分析结果"""
        rsi = analysis.get("RSI", {}).get("RSI", 50)
        macd_trend = analysis.get("MACD", {}).get("趋势", "中性")
        boll_pos = analysis.get("布林带", {}).get("位置", "中")
        
        signals = []
        if rsi < 30: signals.append("RSI超卖")
        elif rsi > 70: signals.append("RSI超买")
        if "多头" in macd_trend and "衰减" not in macd_trend: signals.append("MACD多头")
        elif "空头" in macd_trend: signals.append("MACD空头")
        
        signal_text = "、".join(signals) if signals else "无明确信号"
        
        did = self.journal.record(
            decision_type="etf_analysis_auto",
            input_text=f"{code} 技术分析：RSI={rsi:.1f}, MACD={macd_trend}, 布林={boll_pos}",
            output_text=f"信号：{signal_text}。当前{'观望' if not signals else '关注'}",
            confidence=0.7 if signals else 0.5,
            model_used="prism-auto-analyze",
            metadata={"code": code, "rsi": rsi, "date": datetime.now().strftime("%Y-%m-%d")}
        )
        
        return did
    
    def screening_streak(self) -> Dict:
        """统计连续无标的天数（防守连续正确率）"""
        conn = sqlite3.connect(self.journal.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, output_text, result_accuracy
            FROM decisions 
            WHERE decision_type = 'bond_screening_auto'
            ORDER BY timestamp DESC LIMIT 30
        """)
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return {"streak": 0, "total_screenings": 0}
        
        streak = 0
        for ts, output, acc in rows:
            if "防守正确" in (output or ""):
                streak += 1
            else:
                break
        
        accs = [r[2] for r in rows if r[2] is not None]
        return {
            "streak": streak,
            "total_screenings": len(rows),
            "avg_accuracy": round(sum(accs)/len(accs), 3) if accs else None,
            "conclusion": f"连续{streak}天防守正确" if streak > 0 else "有标的通过筛选"
        }


class StrategyBacktester:
    """
    策略回测器 — 基于决策日志验证历史策略
    
    用历史决策数据验证：
    1. 可转债双低策略的历史胜率
    2. ETF技术分析信号的准确性
    3. 防守策略的长期效果
    4. 置信度校准（是否过度自信）
    """
    
    def __init__(self, journal: DecisionJournal):
        self.journal = journal
    
    def backtest_type(self, decision_type: str) -> Dict:
        """回测某类决策"""
        conn = sqlite3.connect(self.journal.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, confidence, result_accuracy, feedback
            FROM decisions 
            WHERE decision_type = ? AND result_accuracy IS NOT NULL
        """, (decision_type,))
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return {"type": decision_type, "samples": 0}
        
        accs = [r[2] for r in rows]
        confs = [r[1] for r in rows]
        neg_fb = sum(1 for r in rows if r[3] and any(w in (r[3] or "") for w in ["错","不对","不准"]))
        
        calibration = None
        if confs and accs:
            avg_conf = sum(confs) / len(confs)
            avg_acc = sum(accs) / len(accs)
            calibration = {
                "avg_confidence": round(avg_conf, 2),
                "avg_accuracy": round(avg_acc, 2),
                "overconfident": avg_conf > avg_acc + 0.1,
                "underconfident": avg_acc > avg_conf + 0.1,
            }
        
        return {
            "type": decision_type,
            "samples": len(rows),
            "avg_accuracy": round(sum(accs)/len(accs), 3) if accs else None,
            "negative_feedbacks": neg_fb,
            "calibration": calibration,
        }
    
    def backtest_all(self) -> Dict:
        """回测所有决策类型"""
        conn = sqlite3.connect(self.journal.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT decision_type FROM decisions WHERE result_accuracy IS NOT NULL")
        types = [r[0] for r in c.fetchall()]
        conn.close()
        
        results = {}
        overall_accs = []
        for t in types:
            bt = self.backtest_type(t)
            results[t] = bt
            if bt.get("avg_accuracy"):
                overall_accs.append(bt["avg_accuracy"])
        
        return {
            "by_type": results,
            "overall_accuracy": round(sum(overall_accs)/len(overall_accs), 3) if overall_accs else None,
            "total_types": len(types),
            "overconfident_types": [t for t, v in results.items() 
                                    if v.get("calibration", {}).get("overconfident")],
        }
