"""
棱镜大脑API — Prism Brain REST + WebSocket API v2.0
集成永久记忆 + 多模型路由 + 自我进化引擎

端点：
  /brain/chat          POST  聊天接口（自动记录决策日志）
  /brain/ws            WS    WebSocket实时聊天
  /brain/memories      GET   查询记忆
  /brain/memories      POST  写入记忆
  /brain/memories/{id} PUT   更新记忆
  /brain/memories/{id} DELETE 停用记忆
  /brain/stats         GET   记忆统计
  /brain/think         POST  纯推理（不调LLM，只召回记忆+分析）
  /brain/router        GET   多模型路由器状态
  /brain/journal       GET   决策日志
  /brain/journal/{id}/feedback  POST  给决策打分反馈
  /brain/journal/{id}/result   POST  补充实际结果
  /brain/evolve        POST  触发自我进化
  /brain/evolve/auto   GET   自动调参建议
  /brain/agents        GET   多Agent协调器状态
  /brain/auto/screen   POST  自动可转债筛选闭环
  /brain/auto/etf      POST  自动ETF分析闭环
  /brain/auto/streak   GET   防守连续天数
  /brain/backtest      GET   策略回测
  /brain/backtest/{type} GET  单类回测
"""

import os
import sys
import json
import asyncio
from typing import Optional, List
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# 导入棱镜大脑模块
BRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BRAIN_DIR)

from prism_brain import PrismMemory, PrismBrain, init_default_memories
from prism_reasoner import PrismRouter
from prism_evolution import DecisionJournal, SelfEvolver, MultiAgentCoordinator, AutoDecisionLoop, StrategyBacktester

brain_router = APIRouter(prefix="/brain", tags=["brain"])

# 全局实例
memory = PrismMemory()
brain = PrismBrain(memory=memory)
reasoner = PrismRouter()
journal = DecisionJournal()
evolver = SelfEvolver(journal, memory=memory)
coordinator = MultiAgentCoordinator()
auto_loop = AutoDecisionLoop(journal)
backtester = StrategyBacktester(journal)

# ============ 数据模型 ============

class ChatRequest(BaseModel):
    message: str
    use_llm: bool = False
    context: dict = None

class MemoryCreateRequest(BaseModel):
    content: str
    tag: str = "fact:stable"
    trigger_condition: str = ""
    decision_weight: str = "reference"
    expiry_condition: str = "never"
    source: str = "observation"

class MemoryUpdateRequest(BaseModel):
    content: str = None
    tag: str = None
    trigger_condition: str = None
    decision_weight: str = None
    expiry_condition: str = None

class ThinkRequest(BaseModel):
    message: str

class FeedbackRequest(BaseModel):
    feedback: str

class ResultRequest(BaseModel):
    actual: str
    accuracy: float = None

# ============ 记忆端点 ============

@brain_router.get("/stats")
def brain_stats():
    stats = memory.stats()
    return {"status": "ok", "data": stats}

@brain_router.get("/memories")
def list_memories(query: str = "", tag: str = None, weight: str = None, limit: int = 50):
    tags = [tag] if tag else None
    results = memory.recall(query=query, tags=tags, weight=weight, limit=limit)
    return {"count": len(results), "data": results}

@brain_router.post("/memories")
def create_memory(req: MemoryCreateRequest):
    mid = memory.add(
        content=req.content, tag=req.tag,
        trigger_condition=req.trigger_condition,
        decision_weight=req.decision_weight,
        expiry_condition=req.expiry_condition,
        source=req.source
    )
    return {"status": "created", "id": mid}

@brain_router.put("/memories/{memory_id}")
def update_memory(memory_id: int, req: MemoryUpdateRequest):
    memory.update(memory_id, **req.dict(exclude_none=True))
    return {"status": "updated", "id": memory_id}

@brain_router.delete("/memories/{memory_id}")
def deactivate_memory(memory_id: int):
    memory.deactivate(memory_id)
    return {"status": "deactivated", "id": memory_id}

# ============ 推理端点 ============

@brain_router.post("/think")
def think(req: ThinkRequest):
    result = brain.think(req.message)
    weight_icons = {"mandatory": "🔴", "strong": "🟡", "reference": "🔵", "background": "⚪"}
    formatted = []
    for m in result["recalled_memories"]:
        icon = weight_icons.get(m.get("decision_weight", ""), "🔵")
        formatted.append({
            "icon": icon, "tag": m["tag"], "content": m["content"],
            "weight": m["decision_weight"], "trigger": m.get("trigger_condition", ""),
        })
    return {"decision_type": result["decision_type"], "memory_count": result["memory_count"], "memories": formatted}

@brain_router.post("/chat")
def chat(req: ChatRequest):
    """聊天接口 — 自动记录决策日志"""
    think_result = brain.think(req.message)
    memories = think_result["recalled_memories"]
    decision_type = think_result["decision_type"]
    
    if req.use_llm and reasoner._available_models():
        reply, call_meta = reasoner.chat(req.message, memories=memories)
        # 自动记录决策日志
        decision_id = journal.record(
            decision_type=decision_type,
            input_text=req.message,
            output_text=reply,
            memories_recalled=memories,
            model_used=call_meta.get("model", "unknown"),
            cost_yuan=call_meta.get("cost_yuan", 0),
            elapsed_seconds=call_meta.get("elapsed_seconds", 0),
        )
        return {
            "reply": reply,
            "decision_type": decision_type,
            "memories_used": think_result["memory_count"],
            "llm_used": True,
            "model_used": call_meta.get("model", "unknown"),
            "cost_yuan": call_meta.get("cost_yuan", 0),
            "decision_id": decision_id,  # 前端可用此ID反馈结果
        }
    else:
        return {
            "reply": None,
            "decision_type": decision_type,
            "memories_used": think_result["memory_count"],
            "memories": think_result["recalled_memories"],
            "llm_used": False,
            "note": "LLM未启用。设置API Key启用推理（如DEEPSEEK_API_KEY）。",
        }

# ============ 决策日志端点 ============

@brain_router.get("/journal")
def list_decisions(limit: int = 20):
    """最近决策日志"""
    decisions = journal.recent(limit=limit)
    return {"count": len(decisions), "data": decisions}

@brain_router.post("/journal/{decision_id}/feedback")
def give_feedback(decision_id: int, req: FeedbackRequest):
    """给某次决策打分反馈 — L5自我进化的种子"""
    journal.add_feedback(decision_id, req.feedback)
    # 立即尝试从反馈中学习
    lessons = evolver.evolve()
    return {
        "status": "feedback_recorded",
        "decision_id": decision_id,
        "lessons_learned": len(lessons),
        "lessons": lessons[:3] if lessons else [],
    }

@brain_router.post("/journal/{decision_id}/result")
def add_result(decision_id: int, req: ResultRequest):
    """补充决策的实际结果"""
    journal.add_result(decision_id, req.actual, req.accuracy)
    return {"status": "result_recorded", "decision_id": decision_id}

# ============ 自我进化端点 ============

@brain_router.post("/evolve")
def trigger_evolution():
    """手动触发自我进化"""
    lessons = evolver.evolve()
    tune = evolver.auto_tune()
    return {
        "lessons_learned": len(lessons),
        "lessons": lessons[:5],
        "auto_tune": tune,
    }

@brain_router.get("/evolve/auto")
def auto_tune_suggestions():
    """自动调参建议"""
    return evolver.auto_tune()

@brain_router.get("/evolve/stats")
def evolution_stats():
    """进化统计"""
    return journal.accuracy_stats()

# ============ 多Agent端点 ============

@brain_router.get("/agents")
def agent_status():
    """多Agent协调器状态"""
    return coordinator.status()

# ============ WebSocket ============

@brain_router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """WebSocket实时聊天 — iPhone PWA用"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data) if data.startswith("{") else {"message": data}
            user_msg = msg.get("message", "")
            use_llm = msg.get("use_llm", False)
            
            think_result = brain.think(user_msg)
            memories = think_result["recalled_memories"]
            
            if use_llm and reasoner._available_models():
                reply, call_meta = await asyncio.to_thread(reasoner.chat, user_msg, memories)
                decision_id = journal.record(
                    decision_type=think_result["decision_type"],
                    input_text=user_msg, output_text=reply,
                    memories_recalled=memories,
                    model_used=call_meta.get("model", "unknown"),
                    cost_yuan=call_meta.get("cost_yuan", 0),
                    elapsed_seconds=call_meta.get("elapsed_seconds", 0),
                )
                response = {
                    "type": "reply", "content": reply,
                    "decision_type": think_result["decision_type"],
                    "memories_used": think_result["memory_count"],
                    "model_used": call_meta.get("model", "unknown"),
                    "cost_yuan": call_meta.get("cost_yuan", 0),
                    "decision_id": decision_id,
                }
            else:
                weight_icons = {"mandatory": "🔴", "strong": "🟡", "reference": "🔵", "background": "⚪"}
                mem_list = [{"icon": weight_icons.get(m.get("decision_weight",""), "🔵"),
                            "tag": m["tag"], "content": m["content"]} for m in memories]
                response = {"type": "think", "decision_type": think_result["decision_type"],
                           "memories_used": think_result["memory_count"], "memories": mem_list}
            
            await websocket.send_text(json.dumps(response, ensure_ascii=False))
    except WebSocketDisconnect:
        pass

# ============ 状态页 ============

@brain_router.get("")
@brain_router.get("/")
def brain_home():
    stats = memory.stats()
    router_status = reasoner.status()
    evo_stats = journal.accuracy_stats()
    return {
        "name": "棱镜大脑",
        "version": "2.0.0",
        "status": "alive",
        "evolution_level": "L3→L4",
        "memory_stats": stats,
        "router": {"available": router_status["available_models"], "total": router_status["total_models"]},
        "evolution_stats": evo_stats,
        "llm_status": f"{router_status['available_models']} models available" if router_status['available_models'] > 0 else "no_api_key",
        "endpoints": ["/brain/chat", "/brain/ws", "/brain/think", "/brain/memories", 
                      "/brain/stats", "/brain/router", "/brain/journal", 
                      "/brain/evolve", "/brain/evolve/auto", "/brain/agents",
                      "/brain/auto/screen", "/brain/auto/etf", "/brain/auto/streak",
                      "/brain/backtest", "/brain/backtest/{type}"],
    }

@brain_router.get("/router")
def router_status():
    return reasoner.status()


# ============ 自动决策闭环端点 ============

class BondScreenResult(BaseModel):
    total: int = Field(..., description="扫描总数")
    passed: int = Field(..., description="通过筛选数")
    min_double_low: float = Field(..., description="最低双低值")

class ETFAnalysisInput(BaseModel):
    code: str = Field(..., description="ETF代码")
    analysis: dict = Field(..., description="技术分析结果")

@brain_router.post("/auto/screen")
def auto_bond_screen(result: BondScreenResult):
    """自动可转债筛选闭环 — 记录筛选结果，自动判定防守正确性"""
    did = auto_loop.record_bond_screening(result.dict())
    streak = auto_loop.screening_streak()
    return {
        "decision_id": did,
        "streak": streak,
        "status": "recorded"
    }

@brain_router.post("/auto/etf")
def auto_etf_analysis(input: ETFAnalysisInput):
    """自动ETF分析闭环 — 记录技术分析结果"""
    did = auto_loop.record_etf_analysis(input.code, input.analysis)
    return {
        "decision_id": did,
        "status": "recorded"
    }

@brain_router.get("/auto/streak")
def get_streak():
    """防守连续天数 — 可转债连续无符合标的天数"""
    return auto_loop.screening_streak()

@brain_router.get("/backtest")
def backtest_all():
    """策略回测 — 所有决策类型的准确率和校准"""
    return backtester.backtest_all()

@brain_router.get("/backtest/{decision_type}")
def backtest_type(decision_type: str):
    """单类策略回测"""
    return backtester.backtest_type(decision_type)
