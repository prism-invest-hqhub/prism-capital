"""
棱镜大脑API — Prism Brain REST + WebSocket API
集成永久记忆 + LLM推理 + 工具调用

端点：
  /brain/chat          POST  聊天接口
  /brain/ws            WS    WebSocket实时聊天
  /brain/memories      GET   查询记忆
  /brain/memories      POST  写入记忆
  /brain/memories/{id} PUT   更新记忆
  /brain/memories/{id} DELETE 停用记忆
  /brain/stats         GET   记忆统计
  /brain/think         POST  纯推理（不调LLM，只召回记忆+分析）
"""

import os
import sys
import json
import asyncio
from typing import Optional, List
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# 导入棱镜大脑模块
BRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BRAIN_DIR)

from prism_brain import PrismMemory, PrismBrain, init_default_memories
from prism_reasoner import PrismRouter

brain_router = APIRouter(prefix="/brain", tags=["brain"])

# 全局实例
memory = PrismMemory()
brain = PrismBrain(memory=memory)
reasoner = PrismRouter()

# ============ 数据模型 ============

class ChatRequest(BaseModel):
    message: str
    use_llm: bool = False  # 是否调用LLM（默认只召回记忆+分析）
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

# ============ API端点 ============

@brain_router.get("/stats")
def brain_stats():
    """记忆统计"""
    stats = memory.stats()
    return {"status": "ok", "data": stats}

@brain_router.get("/memories")
def list_memories(query: str = "", tag: str = None, weight: str = None, limit: int = 50):
    """查询记忆"""
    tags = [tag] if tag else None
    results = memory.recall(query=query, tags=tags, weight=weight, limit=limit)
    return {"count": len(results), "data": results}

@brain_router.post("/memories")
def create_memory(req: MemoryCreateRequest):
    """写入新记忆"""
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
    """更新记忆"""
    memory.update(memory_id, **req.dict(exclude_none=True))
    return {"status": "updated", "id": memory_id}

@brain_router.delete("/memories/{memory_id}")
def deactivate_memory(memory_id: int):
    """停用记忆（不删除）"""
    memory.deactivate(memory_id)
    return {"status": "deactivated", "id": memory_id}

@brain_router.post("/think")
def think(req: ThinkRequest):
    """纯推理：召回记忆+判断决策类型（不调LLM）"""
    result = brain.think(req.message)
    
    # 格式化输出
    weight_icons = {"mandatory": "🔴", "strong": "🟡", "reference": "🔵", "background": "⚪"}
    formatted = []
    for m in result["recalled_memories"]:
        icon = weight_icons.get(m.get("decision_weight", ""), "🔵")
        formatted.append({
            "icon": icon,
            "tag": m["tag"],
            "content": m["content"],
            "weight": m["decision_weight"],
            "trigger": m.get("trigger_condition", ""),
        })
    
    return {
        "decision_type": result["decision_type"],
        "memory_count": result["memory_count"],
        "memories": formatted
    }

@brain_router.post("/chat")
def chat(req: ChatRequest):
    """聊天接口"""
    # 1. 召回记忆
    think_result = brain.think(req.message)
    memories = think_result["recalled_memories"]
    
    if req.use_llm and reasoner._available_models():
        # 调用LLM推理（多模型路由）
        reply, call_meta = reasoner.chat(req.message, memories=memories)
        return {
            "reply": reply,
            "decision_type": think_result["decision_type"],
            "memories_used": think_result["memory_count"],
            "llm_used": True,
            "model_used": call_meta.get("model", "unknown"),
            "cost_yuan": call_meta.get("cost_yuan", 0),
        }
    else:
        # 只返回记忆召回结果
        return {
            "reply": None,
            "decision_type": think_result["decision_type"],
            "memories_used": think_result["memory_count"],
            "memories": think_result["recalled_memories"],
            "llm_used": False,
            "note": "LLM未启用，仅返回记忆召回。设置API Key环境变量启用LLM推理（如DEEPSEEK_API_KEY）。"
        }

# ============ WebSocket ============

@brain_router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """WebSocket实时聊天 — iPhone PWA用这个"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data) if data.startswith("{") else {"message": data}
            user_msg = msg.get("message", "")
            use_llm = msg.get("use_llm", False)
            
            # 召回记忆
            think_result = brain.think(user_msg)
            memories = think_result["recalled_memories"]
            
            if use_llm and reasoner._available_models():
                # 异步调LLM（多模型路由）
                reply, call_meta = await asyncio.to_thread(reasoner.chat, user_msg, memories)
                response = {
                    "type": "reply",
                    "content": reply,
                    "decision_type": think_result["decision_type"],
                    "memories_used": think_result["memory_count"],
                    "model_used": call_meta.get("model", "unknown"),
                    "cost_yuan": call_meta.get("cost_yuan", 0),
                }
            else:
                # 只返回记忆分析
                weight_icons = {"mandatory": "🔴", "strong": "🟡", "reference": "🔵", "background": "⚪"}
                mem_list = []
                for m in memories:
                    mem_list.append({
                        "icon": weight_icons.get(m.get("decision_weight",""), "🔵"),
                        "tag": m["tag"],
                        "content": m["content"],
                    })
                response = {
                    "type": "think",
                    "decision_type": think_result["decision_type"],
                    "memories_used": think_result["memory_count"],
                    "memories": mem_list,
                }
            
            await websocket.send_text(json.dumps(response, ensure_ascii=False))
    
    except WebSocketDisconnect:
        pass

# ============ Brain状态页 ============

@brain_router.get("")
@brain_router.get("/")
def brain_home():
    """大脑状态页"""
    stats = memory.stats()
    router_status = reasoner.status()
    return {
        "name": "棱镜大脑",
        "version": "2.0.0",
        "status": "alive",
        "memory_stats": stats,
        "router": router_status,
        "llm_status": f"{router_status['available_models']} models available" if router_status['available_models'] > 0 else "no_api_key",
        "endpoints": ["/brain/chat", "/brain/ws", "/brain/think", "/brain/memories", "/brain/stats", "/brain/router"]
    }

@brain_router.get("/router")
def router_status():
    """多模型路由器状态"""
    return reasoner.status()
