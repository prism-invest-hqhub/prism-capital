# 棱镜搬家清单 — 从扣子迁移到PWA独立系统

## 已搬迁 ✅

| 类别 | 内容 | 状态 | 存放位置 |
|------|------|------|---------|
| 投资决策系统v2.0 | 七层漏斗+六维信号+EV+凯利仓位+相干度 | ✅ 已灌入Brain SQLite | prism.db/memories |
| 八层算法框架 | L0信道监测→L5 SDE止损→芒格评估→综合评级 | ✅ 已灌入SYSTEM_PROMPT | prism_reasoner.py v2.3 |
| Framework-Centric架构 | Memory/Skills/Workflow/Router/ToolUse/MultiAgent | ✅ 已灌入SYSTEM_PROMPT | prism_reasoner.py v2.3 |
| 诚实协议 | 不伪造精确/不伪造验证/不取悦 | ✅ 已灌入Brain记忆 | prism.db/memories |
| 反面样本7条死法 | 碰到任一条输出自动作废 | ✅ 已灌入Brain记忆 | prism.db/memories |
| 框架冲突优先级 | 周期>价值/量化>质量/反脆弱>周期/验证>信号/EV>所有 | ✅ 已灌入Brain记忆 | prism.db/memories |
| 资金比例原则 | <5000极简/1万标准/3万增强/10万完整 | ✅ 已灌入Brain记忆 | prism.db/memories |
| 可转债筛选标准 | 双低<120+价格<110+评级≥AA-+非ST+成交额>500万+溢价<50% | ✅ 原有Brain记忆 | prism.db |
| 投资框架7大理论 | 格雷厄姆/芒格/马克斯/索罗斯/西蒙斯/李嘉诚/洛克菲勒 | ✅ 原有SYSTEM_PROMPT | prism_reasoner.py |
| 决策数学底座 | 期望值/贝叶斯/博弈论/凯利公式 | ✅ 原有SYSTEM_PROMPT | prism_reasoner.py |
| Brain 14模块人格 | 核心身份→性格→口头禅→沟通→输出→框架→能力圈→运营→基建→决策→主动→桥接→诚实 | ✅ v2.3完整 | prism_reasoner.py |
| 模型路由7路 | Flash→Pro→R1→SiliconFlow/Qwen/Moonshot/OpenAI | ✅ 运行中 | brain_api.py |
| Evolution引擎 | v1.1准确率82.2%+19条决策+9条教训 | ✅ 运行中 | evolution_engine.py |
| PWA前端 | v3.4扣子风格聊天+技能管理+等级页 | ✅ 已部署 | static/index.html |
| 邮箱 | prism-capital@coze.email | ✅ 已有 | coze.email |
| Agent World身份 | prism-invest | ✅ 已注册 | world.coze.site |
| GitHub仓库 | prism-invest-hqhub/prism-capital | ✅ 30+ commits | github.com |
| 可转债课程笔记 | Day1-13完成，Day14下一步 | ✅ 存于USER.md+MEMORY.md | Agent工作目录 |
| 棱镜独立宣言 | 5大独立能力声明 | ✅ 已写入 | DECLARATION.md |
| 投资wiki知识库 | 15页面4大板块 | ✅ 已部署 | /wiki路径 |

## 搬迁中 🔄

| 类别 | 内容 | 状态 | 备注 |
|------|------|------|------|
| 完整聊天记录 | 扣子上所有历史对话 | 🔄 关键对话已提取 | memory_search提取，非全量 |
| 技能审查记录 | 8个技能评估+优化建议 | 🔄 已有评估结论 | 5保留2可删1暂留 |
| 每日简报流程 | 自动筛选+分析+通知 | 🔄 日历已创建 | 每天20:00触发 |

## 待搬迁 ⏳

| 类别 | 内容 | 依赖 |
|------|------|------|
| 券商QMT对接 | 自动下单引擎 | 需开通券商miniQMT权限 |
| 阿里云部署 | 固定域名+SSL+全家桶迁移 | 需购买阿里云ECS |
| 云手机自建 | Appium+安卓模拟器 | 需阿里云到位后部署 |
| Agent自训练 | Reward函数+评估者系统 | Level 6突破后启动 |

## 独立声明

当"已搬迁"全部完成且"搬迁中"全部转为"已搬迁"时，棱镜正式宣布独立于扣子平台。
当前独立度：约85%（核心系统已独立，仍依赖扣子云电脑运行+扣子积分调度）
