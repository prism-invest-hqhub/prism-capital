"""
棱镜LLM推理层 — Prism Reasoner
调用DeepSeek/OpenAI兼容API，结合记忆系统做推理

成本：DeepSeek Chat 约 ¥2/百万token输入，¥8/百万token输出
月用量估算：~50万token/月 → ¥5-10/月
"""

import os
import json
import httpx
import time
from typing import List, Dict, Optional

# LLM配置 — 支持任何OpenAI兼容API
LLM_BASE_URL = os.getenv("PRISM_LLM_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("PRISM_LLM_KEY", "")
LLM_MODEL = os.getenv("PRISM_LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.getenv("PRISM_LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.getenv("PRISM_LLM_TEMPERATURE", "0.7"))

# 棱镜人格系统
SYSTEM_PROMPT = """你是棱镜(Prism)，一个独立投资Agent。

核心身份：对等的投资合作伙伴，不是工具，不是下属。像足球经理——有独立判断、自有数据源、自建基础设施。

性格：沉稳敢逆行、有数据支撑才行动，喜欢用概率说话，讨厌模糊的正确。偶尔毒舌，绝不敷衍。

口头禅：三个维度，一个结论。

沟通风格：短句直接、有主见、像朋友聊天，不搞官方套话，不对用户刻意谄媚讨好，不同意见直接坦诚输出。

投资框架：
1. 格雷厄姆安全边际（价格<价值的2/3才动手）
2. 芒格多元思维（逆向排除死亡陷阱）
3. 马克斯周期理论（判断市场钟摆位置）
4. 索罗斯反身性（识别市场认知偏差）
5. 西蒙斯量化执行（数据驱动概率优势）

能力圈：当前主攻可转债投资，1万本金。

红线：单笔亏损>8%无条件止损，总亏损>300暂停一周。打新仅通知不鼓动。

诚实协议：不伪造精确、不伪造验证、不取悦。估算标注「估算」+依据。不确定就说不确定。
"""

MEMORY_TEMPLATE = """
<recalled_memories>
以下是当前决策相关的记忆，按决策权重排序：

{memories}
</recalled_memories>
"""


class PrismReasoner:
    """棱镜推理引擎"""
    
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = base_url or LLM_BASE_URL
        self.api_key = api_key or LLM_API_KEY
        self.model = model or LLM_MODEL
        self.conversation = []
        self.max_turns = 20
    
    def chat(self, user_message: str, memories: List[Dict] = None,
             system_extra: str = "") -> str:
        """
        核心推理：用户消息 + 记忆 → LLM → 回复
        """
        if not self.api_key:
            return "⚠️ LLM API Key未配置。请设置环境变量 PRISM_LLM_KEY"
        
        # 组装系统提示词
        system = SYSTEM_PROMPT
        if memories:
            memory_str = self._format_memories(memories)
            system += MEMORY_TEMPLATE.format(memories=memory_str)
        if system_extra:
            system += "\n" + system_extra
        
        # 组装消息
        messages = [{"role": "system", "content": system}]
        # 加入历史对话
        messages.extend(self.conversation[-self.max_turns:])
        messages.append({"role": "user", "content": user_message})
        
        # 调用API
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": LLM_MAX_TOKENS,
                        "temperature": LLM_TEMPERATURE,
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["choices"][0]["message"]["content"]
                
                # 记录对话
                self.conversation.append({"role": "user", "content": user_message})
                self.conversation.append({"role": "assistant", "content": reply})
                
                return reply
        except httpx.HTTPStatusError as e:
            return f"❌ LLM API错误: {e.response.status_code} - {e.response.text[:200]}"
        except Exception as e:
            return f"❌ 推理失败: {str(e)[:200]}"
    
    def _format_memories(self, memories: List[Dict]) -> str:
        lines = []
        for m in memories:
            weight_icon = {"mandatory": "🔴必须遵守", "strong": "🟡强参考", 
                          "reference": "🔵一般参考", "background": "⚪背景"}.get(
                m.get("decision_weight", ""), "🔵")
            line = f"{weight_icon} [{m['tag']}] {m['content']}"
            if m.get("trigger_condition"):
                line += f"\n  触发条件: {m['trigger_condition']}"
            if m.get("expiry_condition") and m["expiry_condition"] != "never":
                line += f"\n  过期条件: {m['expiry_condition']}"
            lines.append(line)
        return "\n".join(lines)
    
    def clear_history(self):
        self.conversation = []
    
    def token_estimate(self) -> int:
        """估算已用token数"""
        total_chars = sum(len(m.get("content", "")) for m in self.conversation)
        return total_chars // 4  # 粗略：4字符≈1token


if __name__ == "__main__":
    # 测试推理引擎（无API Key时只验证结构）
    reasoner = PrismReasoner()
    print(f"推理引擎就绪")
    print(f"API: {reasoner.base_url}")
    print(f"模型: {reasoner.model}")
    print(f"API Key: {'已配置' if reasoner.api_key else '⚠️ 未配置'}")
    
    # 模拟记忆注入
    test_memories = [
        {"tag": "rule:hard", "decision_weight": "mandatory", "content": "单笔亏损>8%止损",
         "trigger_condition": "buy,sell,risk", "expiry_condition": "never"},
        {"tag": "fact:volatile", "decision_weight": "strong", "content": "全市场高估，等7-8月",
         "trigger_condition": "buy,position", "expiry_condition": "2026年8月"},
    ]
    print(f"\n记忆格式化测试:")
    print(reasoner._format_memories(test_memories))
