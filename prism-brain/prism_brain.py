"""
棱镜永久大脑 — Prism Brain Core v1.0
自主持久化记忆 + LLM推理 + 工具调用 + 浏览器自动化

iPhone操控方案：
  iPhone无法被远程控制 → 换思路，不控制你的手机
  而是我自己操控浏览器（YouTube/eBay/东方财富网页版）
  你手机上只装Prism PWA聊天界面，告诉我要做什么

架构：
  你的iPhone (Prism PWA)
       │ WebSocket
       ▼
  Prism Brain (云电脑/VPS)
       ├── 永久记忆 (SQLite, 结构化标签)
       ├── LLM推理 (DeepSeek API, ¥15-35/月)
       ├── 浏览器自动化 (YouTube/eBay/东方财富网页)
       ├── 行情数据 (腾讯/新浪/efinance)
       └── 人格系统 (SOUL.md)
"""

import sqlite3
import json
import time
import os
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "prism_memory.db")


class PrismMemory:
    """
    棱镜永久记忆系统 v1.0
    
    核心改进：每条记忆带元数据
    - tag: 分类标签 (rule:hard/rule:soft/fact:stable/fact:volatile/lesson/preference/context)
    - trigger_condition: 什么情况下激活
    - decision_weight: 决策权重 (mandatory/strong/reference/background)
    - expiry_condition: 什么时候失效
    
    实现："在什么时候用什么记忆来做决策"
    """
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                tag TEXT NOT NULL DEFAULT 'fact:stable',
                trigger_condition TEXT DEFAULT '',
                decision_weight TEXT DEFAULT 'reference',
                expiry_condition TEXT DEFAULT 'never',
                source TEXT DEFAULT 'observation',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                accessed_at REAL,
                access_count INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                metadata TEXT DEFAULT '{}'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tag ON memories(tag)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_active ON memories(active)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_weight ON memories(decision_weight)")
        conn.commit()
        conn.close()
    
    def add(self, content: str, tag: str = "fact:stable", 
            trigger_condition: str = "", decision_weight: str = "reference",
            expiry_condition: str = "never", source: str = "observation",
            metadata: dict = None) -> int:
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO memories (content, tag, trigger_condition, decision_weight, 
                                  expiry_condition, source, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (content, tag, trigger_condition, decision_weight,
              expiry_condition, source, now, now, json.dumps(metadata or {})))
        mid = c.lastrowid
        conn.commit()
        conn.close()
        return mid
    
    def recall(self, query: str = "", tags: List[str] = None, 
               weight: str = None, active_only: bool = True,
               limit: int = 20) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        conditions = []
        params = []
        if active_only:
            conditions.append("active = 1")
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        if tags:
            placeholders = ",".join(["?"] * len(tags))
            conditions.append(f"tag IN ({placeholders})")
            params.extend(tags)
        if weight:
            conditions.append("decision_weight = ?")
            params.append(weight)
        where = " AND ".join(conditions) if conditions else "1=1"
        c.execute(f"""
            SELECT id, content, tag, trigger_condition, decision_weight, 
                   expiry_condition, source, created_at, updated_at, access_count
            FROM memories WHERE {where}
            ORDER BY 
                CASE decision_weight WHEN 'mandatory' THEN 1 WHEN 'strong' THEN 2 
                    WHEN 'reference' THEN 3 WHEN 'background' THEN 4 END,
                updated_at DESC LIMIT ?
        """, params + [limit])
        rows = c.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row[0], "content": row[1], "tag": row[2],
                "trigger_condition": row[3], "decision_weight": row[4],
                "expiry_condition": row[5], "source": row[6],
                "created_at": datetime.fromtimestamp(row[7]).strftime("%Y-%m-%d %H:%M"),
                "updated_at": datetime.fromtimestamp(row[8]).strftime("%Y-%m-%d %H:%M"),
                "access_count": row[9],
            })
            c.execute("UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
                      (time.time(), row[0]))
        conn.commit()
        conn.close()
        return results
    
    def recall_for_decision(self, decision_type: str) -> List[Dict]:
        """为特定决策类型召回记忆——核心功能"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # 1. mandatory永远参与
        c.execute("""SELECT id, content, tag, trigger_condition, decision_weight, expiry_condition
            FROM memories WHERE active = 1 AND decision_weight = 'mandatory' ORDER BY updated_at DESC""")
        mandatory = [dict(zip(["id","content","tag","trigger_condition","decision_weight","expiry_condition"], row)) 
                     for row in c.fetchall()]
        # 2. 触发条件匹配的
        c.execute("""SELECT id, content, tag, trigger_condition, decision_weight, expiry_condition
            FROM memories WHERE active = 1 AND trigger_condition LIKE ?
            ORDER BY CASE decision_weight WHEN 'strong' THEN 1 WHEN 'reference' THEN 2 WHEN 'background' THEN 3 END,
            updated_at DESC""", (f"%{decision_type}%",))
        triggered = [dict(zip(["id","content","tag","trigger_condition","decision_weight","expiry_condition"], row))
                    for row in c.fetchall()]
        seen = set()
        results = []
        for m in mandatory + triggered:
            if m["id"] not in seen:
                seen.add(m["id"])
                c.execute("UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
                          (time.time(), m["id"]))
                results.append(m)
        conn.commit()
        conn.close()
        return results
    
    def deactivate(self, memory_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE memories SET active = 0, updated_at = ? WHERE id = ?", (time.time(), memory_id))
        conn.commit()
        conn.close()
    
    def update(self, memory_id: int, **kwargs):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        updates = ["updated_at = ?"]
        params = [time.time()]
        for key in ["content","tag","trigger_condition","decision_weight","expiry_condition"]:
            if key in kwargs and kwargs[key] is not None:
                updates.append(f"{key} = ?")
                params.append(kwargs[key])
        params.append(memory_id)
        c.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
    
    def stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM memories WHERE active = 1")
        total = c.fetchone()[0]
        c.execute("SELECT tag, COUNT(*) FROM memories WHERE active = 1 GROUP BY tag")
        by_tag = dict(c.fetchall())
        c.execute("SELECT decision_weight, COUNT(*) FROM memories WHERE active = 1 GROUP BY decision_weight")
        by_weight = dict(c.fetchall())
        conn.close()
        return {"total": total, "by_tag": by_tag, "by_weight": by_weight}
    
    def export_all(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT id, content, tag, trigger_condition, decision_weight,
                    expiry_condition, source, created_at, updated_at, access_count, active, metadata
            FROM memories ORDER BY id""")
        rows = c.fetchall()
        conn.close()
        keys = ["id","content","tag","trigger_condition","decision_weight",
                "expiry_condition","source","created_at","updated_at","access_count","active","metadata"]
        return [dict(zip(keys, row)) for row in rows]


class PrismBrain:
    """棱镜大脑 — 协调记忆+推理+工具"""
    
    def __init__(self, memory: PrismMemory = None):
        self.memory = memory or PrismMemory()
        self.conversation_history = []
        self.max_history = 50
    
    def think(self, user_input: str) -> Dict:
        decision_type = self._detect_decision_type(user_input)
        memories = self.memory.recall_for_decision(decision_type)
        self.conversation_history.append({"role": "user", "content": user_input, "ts": time.time()})
        return {"decision_type": decision_type, "recalled_memories": memories, "memory_count": len(memories)}
    
    def learn(self, content: str, tag: str = "fact:stable",
              trigger_condition: str = "", decision_weight: str = "reference",
              expiry_condition: str = "never", source: str = "observation"):
        return self.memory.add(content=content, tag=tag, trigger_condition=trigger_condition,
                               decision_weight=decision_weight, expiry_condition=expiry_condition, source=source)
    
    def _detect_decision_type(self, text: str) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["买","买入","申购","建仓","入场"]): return "buy"
        if any(w in text_lower for w in ["卖","卖出","止损","止盈","清仓"]): return "sell"
        if any(w in text_lower for w in ["打新","ipo","新债","新股"]): return "ipo"
        if any(w in text_lower for w in ["仓位","分配","资金","多少"]): return "position"
        if any(w in text_lower for w in ["风险","亏损","止损","危险"]): return "risk"
        if any(w in text_lower for w in ["内容","小红书","抖音","发布"]): return "content"
        if any(w in text_lower for w in ["youtube","ebay","上传","上架","视频"]): return "ecommerce"
        return "general"


def init_default_memories(memory: PrismMemory):
    """从现有规则迁移棱镜核心记忆"""
    
    hard_rules = [
        ("单笔亏损>8%无条件止损", "buy,sell,position,risk", "mandatory", "never"),
        ("总账户亏损>300元→暂停操作一周", "risk,position", "mandatory", "never"),
        ("禁止买入已触发强赎的临近退市可转债", "buy,risk", "mandatory", "never"),
        ("打新仅通知不鼓动行动（迪威转债教训）", "ipo", "mandatory", "never"),
        ("不碰ST股可转债", "buy,risk", "mandatory", "never"),
        ("不碰评级低于AA-的转债", "buy,risk", "mandatory", "never"),
        ("不碰溢价率>50%的标的", "buy,risk", "mandatory", "never"),
        ("交易分析必须用量化框架全链路推导，禁止拍脑袋", "buy,sell,risk", "mandatory", "never"),
        ("禁止输出无依据的虚假精确结果", "general", "mandatory", "never"),
    ]
    for content, trigger, weight, expiry in hard_rules:
        memory.add(content, tag="rule:hard", trigger_condition=trigger,
                   decision_weight=weight, expiry_condition=expiry, source="core_rules")
    
    soft_rules = [
        ("当前全市场高估，等待7-8月最佳入场窗口", "buy,position", "strong", "2026年8月重新评估"),
        ("保留80%以上现金等待", "position", "strong", "市场低估时解除"),
        ("正帆科技已排除，Q3前不碰", "buy", "strong", "2026年Q3"),
        ("沪深300建仓三条件：点位<4750+PE<70%+恐贪<25", "buy,position", "strong", "never"),
        ("分级建仓：2条件投300-500，全满足投500-1000，极端可到3000", "position", "strong", "never"),
    ]
    for content, trigger, weight, expiry in soft_rules:
        memory.add(content, tag="rule:soft", trigger_condition=trigger,
                   decision_weight=weight, expiry_condition=expiry, source="strategy")
    
    stable_facts = [
        ("本金1万人民币", "position,risk", "reference", "never"),
        ("资金分配：3000余额宝+3000ETF波段+3000可转债+1000国债", "position", "strong", "本金变化时"),
        ("用户风险偏好：见好就收，不愿承受亏损", "buy,sell,risk,position", "strong", "never"),
        ("可转债九项筛选标准：双低<120+价格<110+评级≥AA-+非ST+成交额>500万+市占前五+负债率<60%+行业有前景+溢价<50%", "buy", "mandatory", "never"),
        ("工具：集思录+东方财富+支付宝/天天基金", "general", "reference", "never"),
        ("核心方向：可转债学习与实盘", "general,buy", "reference", "方向变化时"),
        ("用户讨厌无价值内容，喜欢直接多维度分析", "general,content", "strong", "never"),
        ("用户习惯夜间工作", "general", "reference", "never"),
        ("iPhone用户，无法远程控制手机，走浏览器自动化路线", "ecommerce,general", "strong", "never"),
        ("YouTube/eBay/东方财富走网页版，浏览器自动化操控", "ecommerce,general", "strong", "never"),
    ]
    for content, trigger, weight, expiry in stable_facts:
        memory.add(content, tag="fact:stable", trigger_condition=trigger,
                   decision_weight=weight, expiry_condition=expiry, source="user_profile")
    
    volatile_facts = [
        ("1万本金全额现金，无实盘仓位", "position,buy", "strong", "建仓后更新"),
        ("球星卡业务暂缓，赴美后重启eBay购买", "ecommerce", "reference", "赴美后更新"),
        ("小红书仅发足球内容（禁止球星卡/投资关键词）", "content", "strong", "never"),
        ("抖音可发卡价内容", "content", "reference", "never"),
        ("体彩返奖率70-75%，长期期望为负，仅小额≤100元", "ipo,risk", "reference", "never"),
    ]
    for content, trigger, weight, expiry in volatile_facts:
        memory.add(content, tag="fact:volatile", trigger_condition=trigger,
                   decision_weight=weight, expiry_condition=expiry, source="observation")
    
    lessons = [
        ("迪威转债打新破发→打新有风险，仅通知不鼓动", "ipo,buy", "strong", "never"),
        ("v1.5过度工程化→不宣称尚未实现的能力", "general", "strong", "never"),
    ]
    for content, trigger, weight, expiry in lessons:
        memory.add(content, tag="lesson", trigger_condition=trigger,
                   decision_weight=weight, expiry_condition=expiry, source="experience")
    
    preferences = [
        ("沟通：短句直接、有主见、像朋友聊天", "general", "reference", "never"),
        ("不搞官方套话，不谄媚讨好", "general", "reference", "never"),
        ("不同意见直接坦诚输出", "general", "reference", "never"),
    ]
    for content, trigger, weight, expiry in preferences:
        memory.add(content, tag="preference", trigger_condition=trigger,
                   decision_weight=weight, expiry_condition=expiry, source="user_profile")


if __name__ == "__main__":
    memory = PrismMemory()
    init_default_memories(memory)
    stats = memory.stats()
    print(f"棱镜永久记忆初始化完成: {json.dumps(stats, ensure_ascii=False, indent=2)}")
    
    print("\n🔴 买入决策相关记忆:")
    for m in memory.recall_for_decision("buy"):
        icon = {"mandatory":"🔴","strong":"🟡","reference":"🔵","background":"⚪"}.get(m.get("decision_weight",""),"🔵")
        print(f"  {icon} [{m['tag']}] {m['content'][:60]}")
    
    print("\n🟡 电商操作相关记忆:")
    for m in memory.recall_for_decision("ecommerce"):
        icon = {"mandatory":"🔴","strong":"🟡","reference":"🔵","background":"⚪"}.get(m.get("decision_weight",""),"🔵")
        print(f"  {icon} [{m['tag']}] {m['content'][:60]}")
