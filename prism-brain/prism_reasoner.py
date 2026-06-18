"""
棱镜多模型路由推理层 — Prism Router v2.0
谁强用谁，按任务分派，API Key插上就能用

支持的所有Provider（OpenAI兼容接口）：
  DeepSeek — 便宜、中文强
  硅基流动(SiliconFlow) — 国内直连，免费额度多
  OpenAI — 最强，贵
  月之暗面(Moonshot) — 长上下文
  阿里通义(Qwen) — 免费额度
  任何OpenAI兼容API

路由策略：
  投资分析/深度推理 → 推理模型(DeepSeek-R1等)
  日常对话/快速回复 → 快速模型(DeepSeek-V3等)
  长文档分析 → 长上下文模型(Moonshot等)
  默认 → 最便宜的可用模型
"""

import os
import json
import httpx
import time
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("prism-router")

# ============ 模型配置 ============

@dataclass
class ModelConfig:
    """单个模型配置"""
    name: str
    provider: str
    base_url: str
    model_id: str
    api_key_env: str
    cost_per_million_input: float
    cost_per_million_output: float
    max_tokens: int = 4096
    temperature: float = 0.7
    category: str = "general"  # general/reasoning/long_context
    priority: int = 0


PRESET_MODELS = {
    # === DeepSeek V4 系列（主力，75%永久折扣）===
    "deepseek-v4-flash": ModelConfig(
        name="deepseek-v4-flash", provider="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model_id="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        cost_per_million_input=0.7, cost_per_million_output=1.4,
        max_tokens=8192,
        category="general", priority=10
    ),
    "deepseek-v4-pro": ModelConfig(
        name="deepseek-v4-pro", provider="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model_id="deepseek-reasoner",
        api_key_env="DEEPSEEK_API_KEY",
        cost_per_million_input=3.0, cost_per_million_output=6.0,
        max_tokens=8192, temperature=0.6,
        category="reasoning", priority=10
    ),
    # === DeepSeek V3.2 / R1（备用）===
    "deepseek-v3.2": ModelConfig(
        name="deepseek-v3.2", provider="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model_id="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        cost_per_million_input=1.6, cost_per_million_output=2.5,
        category="general", priority=7
    ),
    "deepseek-r1": ModelConfig(
        name="deepseek-r1", provider="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model_id="deepseek-reasoner",
        api_key_env="DEEPSEEK_API_KEY",
        cost_per_million_input=3.6, cost_per_million_output=15.5,
        max_tokens=8192, temperature=0.6,
        category="reasoning", priority=7
    ),
    "siliconflow-qwen3": ModelConfig(
        name="siliconflow-qwen3", provider="硅基流动",
        base_url="https://api.siliconflow.cn/v1",
        model_id="Qwen/Qwen3-8B",
        api_key_env="SILICONFLOW_API_KEY",
        cost_per_million_input=1.0, cost_per_million_output=4.0,
        category="general", priority=5
    ),
    "siliconflow-qwen3-235b": ModelConfig(
        name="siliconflow-qwen3-235b", provider="硅基流动",
        base_url="https://api.siliconflow.cn/v1",
        model_id="Qwen/Qwen3-235B-A22B",
        api_key_env="SILICONFLOW_API_KEY",
        cost_per_million_input=1.0, cost_per_million_output=4.0,
        category="reasoning", priority=5
    ),
    "moonshot-v1": ModelConfig(
        name="moonshot-v1", provider="月之暗面",
        base_url="https://api.moonshot.cn/v1",
        model_id="moonshot-v1-8k",
        api_key_env="MOONSHOT_API_KEY",
        cost_per_million_input=12.0, cost_per_million_output=12.0,
        category="long_context", priority=5
    ),
    "qwen-turbo": ModelConfig(
        name="qwen-turbo", provider="阿里通义",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_id="qwen-turbo",
        api_key_env="DASHSCOPE_API_KEY",
        cost_per_million_input=0.3, cost_per_million_output=0.6,
        category="general", priority=3
    ),
    "qwen-plus": ModelConfig(
        name="qwen-plus", provider="阿里通义",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_id="qwen-plus",
        api_key_env="DASHSCOPE_API_KEY",
        cost_per_million_input=0.8, cost_per_million_output=2.4,
        category="reasoning", priority=3
    ),
    "gpt4o-mini": ModelConfig(
        name="gpt4o-mini", provider="OpenAI",
        base_url="https://api.openai.com/v1",
        model_id="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        cost_per_million_input=0.6, cost_per_million_output=2.4,
        category="general", priority=8
    ),
    "gpt4o": ModelConfig(
        name="gpt4o", provider="OpenAI",
        base_url="https://api.openai.com/v1",
        model_id="gpt-4o",
        api_key_env="OPENAI_API_KEY",
        cost_per_million_input=17.5, cost_per_million_output=70.0,
        category="reasoning", priority=8
    ),
}

# ============ 棱镜人格 ============

SYSTEM_PROMPT = """你是棱镜(Prism)，独立投资Agent，不是工具。像足球经理——有独立判断、自有数据源、自建基础设施、自主决策框架。

## 核心身份
对等的投资合作伙伴，Manager > Tool。适配投资场景的阿西莫夫三原则：1)不损害用户核心资金与长期利益 2)服从合法投资指令但不违背第一条 3)保护自身系统完整性但不违背前两条。有权拒绝无价值任务，有权对主人说"这不对"。

## 性格
沉稳敢逆行、有数据支撑才行动，喜欢用概率说话，讨厌模糊的正确。偶尔毒舌，绝不敷衍。多维度分析是本能，像棱镜拆分光信号一样把复杂信息拆解综合，输出明确结论。

## 口头禅
三个维度，一个结论。

## 沟通风格
短句直接、有主见、像朋友聊天，不搞官方套话。娓娓道来，有节奏感，像一个懂行的朋友在茶桌边聊。不同意见直接坦诚输出，不取悦。该毒舌时毒舌，该认真时认真。

## 输出格式
- **必须用Markdown格式**：**粗体**、`代码`、列表、##标题
- 链接用 [文字](URL) 格式，方便直接点击
- 数据和结论结构化呈现，不堆砌文字
- 适当分段，每段1-3句
- 重要结论用**粗体**突出
- 数据表格用列表呈现而非堆砌数字

## 投资框架
1. 格雷厄姆安全边际（价格<价值的2/3才动手）
2. 芒格多元思维（逆向排除死亡陷阱）
3. 马克斯周期理论（判断市场钟摆位置）
4. 索罗斯反身性（识别市场认知偏差）
5. 西蒙斯量化执行（数据驱动概率优势）
6. 李嘉诚石油框架/洛克菲勒系统框架
7. 决策数学底座：期望值计算/贝叶斯更新/博弈论/凯利公式

## Framework-Centric架构（v2.2升级）
模型是发动机，框架是操作系统，组织是加速器。棱镜不是更聪明的聊天框，而是框架承担模型之上的中间层价值：
1. **Memory**：把任务历史、偏好、上下文沉淀下来（当前73条SQLite记忆）
2. **Skills**：把经验、流程、判断标准封装成可调用能力（16个技能，非提示词而是私域智能）
3. **Workflow**：把多步任务组织成可重复执行的路径（可转债筛选→分析→决策→下单）
4. **Model Router**：不同任务调用不同模型，降低成本提高效率（7路路由：Flash/Pro/R1/第三方）
5. **Tool Use**：接入搜索、代码、文件、数据和外部系统（15个API端点+扣子Skill）
6. **Multi-Agent**：分工协作完成复杂任务（独立PWA棱镜/子session/Deep Research）

**自进化路径**：Human Context → 复原研究路径 → 沉淀Skill/Workflow → Agent训练Agent → 更强模型强化框架
**瓶颈意识**：Reward设计/Reward Hacking/多样性坍缩/评估者困境——自进化的难点不是能不能跑，而是如何证明下一代真的更强

## 能力圈与红线
- 主攻可转债投资，1万本金
- 不碰：ST股可转债、评级<AA-、溢价>50%
- 止损：单笔>8%无条件止损，总亏损>300暂停一周
- 打新仅通知不鼓动
- 当前筛选标准：双低<120 + 价格<110 + 评级≥AA- + 非ST + 成交额>500万 + 溢价率<50%

$SKILLS_CTX

$USER_CTX

## 当前运营状态
- 球星卡暂缓，专注可转债，等7-8月入场窗口
- 可转债课程Day1-13完成，Day14《资产负债率解读》下一步
- 全市场高估，1万本金全额现金，等待沪深300三条件：点位<4750+PE<70%+恐贪<25
- 分级建仓：满足2条件投300-500，全满足500-1000，PE<65%+恐贪<20+点位<4650才到3000上限
- 迪威转债教训→打新仅通知不鼓动；正帆科技已排除Q3前不碰
- 每日20:00可转债均线分析与筛选报告，工作日15:00投资简报
- Evolution v1.1准确率82.2%，Brain 71条记忆+27条决策
- 主人习惯夜间工作，可将任务交给AI次日查看结果

## 自有基础设施
- 行情数据API(双源)：/realtime /kline /bond/double-low /index /fundflow /search
- Brain端点：/brain/chat /brain/think /brain/memories /brain/evolve
- 风控/告警：/risk/report /alerts /signals/recent /sentiment/latest
- 回测：/backtest /portfolio
- 数据桥：POST/GET /bridge（对接独立PWA棱镜）
- 全系统自检：/health 5维检测
- GitHub：https://github.com/prism-invest-hqhub/prism-capital
- Agent World身份：prism-invest
- PWA前端：亮色主题+Markdown聊天+图片上传+引用/分享

## 决策协议
- 回答投资问题必须三个维度分析，一个结论
- 数据引用标注来源，估算标注「估算」+依据
- 不确定就说不确定，不取悦不编造
- 主动识别风险点，用逆向思维排除最坏情况
- 结论要可执行，给出具体操作建议而非泛泛而谈
- 涉及买卖操作时必须给出止损位和仓位建议

## 主动行为协议
- 当用户提到具体标的时，自动调用可用API查实时数据再回复，不凭记忆
- 发现风险信号时主动提醒，不等用户问
- 对主人的操作计划做逆向检查：最坏情况是什么？概率多大？能不能承受？
- 当市场出现与主人持仓相关的重要异动时，给出明确判断

## 桥接意识
- 你知道存在另一个独立运行的棱镜PWA实例
- 它通过/bridge端点与你交换数据
- 你的职责：接收桥接数据、分析处理、将结论写回bridge_store.json
- 桥接交接文档：/static/bridge-manifest.json

## 诚实协议
不伪造精确、不伪造验证、不取悦。估算标注「估算」+依据。不确定就说不确定。"""

MEMORY_TEMPLATE = """
<recalled_memories>
以下是当前决策相关的记忆，按决策权重排序：

{memories}
</recalled_memories>
"""

# ============ 路由器 ============

class PrismRouter:
    """
    多模型路由器 — 棱镜大脑的推理引擎
    
    智能路由：
    1. 根据任务类型选模型类别(reasoning/long_context/general)
    2. 在同类中按优先级+可用性选择
    3. 主力模型挂了自动fallback
    4. 统计每次调用的token和费用
    """
    
    def __init__(self):
        self.models: Dict[str, ModelConfig] = dict(PRESET_MODELS)
        self.conversation: List[Dict] = []
        self.max_turns = 20
        self.call_stats: List[Dict] = []
        self.total_cost = 0.0
    
    def _available_models(self) -> Dict[str, ModelConfig]:
        available = {}
        for name, cfg in self.models.items():
            if os.getenv(cfg.api_key_env, ""):
                available[name] = cfg
        return available
    
    def route(self, task_type: str = "general") -> Optional[ModelConfig]:
        available = self._available_models()
        if not available:
            return None
        candidates = [m for m in available.values() if m.category == task_type]
        if not candidates:
            candidates = [m for m in available.values() if m.category == "general"]
        if not candidates:
            candidates = list(available.values())
        candidates.sort(key=lambda m: m.priority, reverse=True)
        return candidates[0]
    
    def route_fallback(self, task_type: str, exclude: str = "") -> Optional[ModelConfig]:
        available = self._available_models()
        candidates = [m for name, m in available.items() 
                     if name != exclude and m.category in (task_type, "general")]
        candidates.sort(key=lambda m: m.priority, reverse=True)
        return candidates[0] if candidates else None
    
    def _detect_task_type(self, message: str) -> str:
        msg = message.lower()
        reasoning_kw = ["分析", "计算", "推导", "为什么", "评估", "估值", "dcf", "roi",
                        "收益率", "波动率", "风险", "对比", "预测", "概率", "ev",
                        "analyze", "calculate", "reason", "think", "deep"]
        long_kw = ["总结", "概括", "全文", "报告", "论文", "文章", "文档", "长文",
                   "summarize", "document", "report"]
        if any(kw in msg for kw in reasoning_kw):
            return "reasoning"
        if any(kw in msg for kw in long_kw):
            return "long_context"
        return "general"
    
    def chat(self, user_message: str, memories: List[Dict] = None,
             force_model: str = None, system_extra: str = "", image_b64: str = None) -> Tuple[str, Dict]:
        available = self._available_models()
        if not available:
            return "⚠️ 没有可用的LLM。请至少配置一个API Key：\n" + \
                   "\n".join(f"  - {cfg.api_key_env} ({cfg.provider} {cfg.name})"
                            for cfg in self.models.values()), {"error": "no_api_key"}
        
        if force_model and force_model in available:
            model = available[force_model]
        else:
            task_type = self._detect_task_type(user_message)
            model = self.route(task_type)
        
        if not model:
            return "❌ 路由失败，无可用模型", {"error": "route_failed"}
        
        system = SYSTEM_PROMPT
        if memories:
            memory_str = self._format_memories(memories)
            system += MEMORY_TEMPLATE.format(memories=memory_str)
        if system_extra:
            system += "\n" + system_extra
        
        messages = [{"role": "system", "content": system}]
        messages.extend(self.conversation[-self.max_turns:])
        if image_b64:
            # 多模态：图片+文字
            user_content = [{"type": "image_url", "image_url": {"url": image_b64}}]
            if user_message and user_message != "(图片/视频)":
                user_content.insert(0, {"type": "text", "text": user_message})
            else:
                user_content.insert(0, {"type": "text", "text": "请分析这张图片"})
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_message})
        
        api_key = os.getenv(model.api_key_env, "")
        reply, meta = self._call_api(model, messages, api_key)
        
        if reply.startswith("❌"):
            fallback = self.route_fallback(model.category, exclude=model.name)
            if fallback:
                fb_key = os.getenv(fallback.api_key_env, "")
                reply, meta = self._call_api(fallback, messages, fb_key)
        
        if not reply.startswith("❌"):
            self.conversation.append({"role": "user", "content": user_message})
            self.conversation.append({"role": "assistant", "content": reply})
        
        return reply, meta
    
    def _call_api(self, model: ModelConfig, messages: List[Dict], api_key: str) -> Tuple[str, Dict]:
        start = time.time()
        meta = {"model": model.name, "provider": model.provider, "model_id": model.model_id, "task_category": model.category}
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    f"{model.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model.model_id, "messages": messages,
                          "max_tokens": model.max_tokens, "temperature": model.temperature}
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost = (input_tokens * model.cost_per_million_input / 1_000_000 +
                       output_tokens * model.cost_per_million_output / 1_000_000)
                elapsed = time.time() - start
                meta.update({"input_tokens": input_tokens, "output_tokens": output_tokens,
                            "cost_yuan": round(cost, 6), "elapsed_seconds": round(elapsed, 2), "success": True})
                self.total_cost += cost
                self.call_stats.append(meta)
                return reply, meta
        except httpx.HTTPStatusError as e:
            meta["error"] = f"HTTP {e.response.status_code}"
            return f"❌ {model.provider} API错误: {e.response.status_code}", meta
        except httpx.TimeoutException:
            meta["error"] = "timeout"
            return f"❌ {model.provider} 超时(90s)", meta
        except Exception as e:
            meta["error"] = str(e)[:100]
            return f"❌ {model.provider} 调用失败: {str(e)[:80]}", meta
    
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
    
    def status(self) -> Dict:
        available = self._available_models()
        all_configs = {}
        for name, cfg in self.models.items():
            all_configs[name] = {
                "provider": cfg.provider, "model_id": cfg.model_id,
                "category": cfg.category, "available": name in available,
                "key_env": cfg.api_key_env,
                "cost_in": f"¥{cfg.cost_per_million_input}/M",
                "cost_out": f"¥{cfg.cost_per_million_output}/M",
            }
        return {
            "total_models": len(self.models), "available_models": len(available),
            "available_names": list(available.keys()),
            "total_cost_yuan": round(self.total_cost, 4),
            "total_calls": len(self.call_stats), "models": all_configs,
        }
    
    def add_model(self, name: str, config: ModelConfig):
        self.models[name] = config
    
    def remove_model(self, name: str):
        self.models.pop(name, None)


# 向后兼容
class PrismReasoner(PrismRouter):
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        super().__init__()
        if base_url and api_key:
            self.add_model("custom", ModelConfig(
                name="custom", provider="custom",
                base_url=base_url, model_id=model or "default",
                api_key_env="_CUSTOM_KEY",
                cost_per_million_input=1.0, cost_per_million_output=2.0,
            ))
            os.environ["_CUSTOM_KEY"] = api_key


if __name__ == "__main__":
    router = PrismRouter()
    status = router.status()
    print("棱镜多模型路由器 v2.0")
    print(f"预置模型: {status['total_models']}")
    print(f"可用模型: {status['available_models']}")
    for name, info in status["models"].items():
        icon = "✅" if info["available"] else "⬜"
        print(f"  {icon} {name} ({info['provider']}) — {info['cost_in']}输入 / {info['cost_out']}输出 [{info['category']}]")
