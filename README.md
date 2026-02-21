# DataForge AI · Multi-Agent 数据分析系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-green.svg)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue%203-Frontend-4FC08D.svg)](https://vuejs.org/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Memory-orange.svg)](https://www.trychroma.com/)
[![Ruff](https://img.shields.io/badge/Ruff-Linter-261230.svg)](https://docs.astral.sh/ruff/)
[![Tests](https://img.shields.io/badge/Tests-57%20passed-brightgreen.svg)](.)

7 个 AI Agent 通过**任务规划 → 工具调用 → 对抗辩论 → 裁判验证**四阶段协作，将 CSV 数据自动转化为带图表的分析报告。内置 ChromaDB 上下文记忆、自适应缓存、多 Provider Embedding 降级和 Token 用量追踪。

---

## 目录

- [架构概览](#-架构概览)
- [快速启动](#-快速启动)
- [项目结构](#-项目结构)
- [数据集说明](#-数据集说明)
- [使用指南](#-使用指南)
- [技术特性](#-技术特性)
- [LLM 配置](#-llm-配置)
- [启动脚本](#-启动脚本)
- [测试](#-测试)
- [面试问答](#-面试问答)

---

## 🧠 架构概览

### 整体流程

```
用户: "哪个品牌性价比最高？"
                │
     ┌──────────▼──────────┐
     │  ① Planner          │  deep_think_llm  拆解为 4 个执行步骤
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  ② SQL Agent        │  quick_think_llm + bind_tools
     │  ←→ tools_sql       │  查表结构→生成SQL→执行→查错修正（自动重试 ≤2次）
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  ③ Chart Agent      │  quick_think_llm + bind_tools
     │  ←→ tools_chart     │  数据→Plotly 柱状图/折线图/散点图
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  ④ Report Agent     │  汇总 SQL 结果 + 图表 → Markdown 报告
     └──────────┬──────────┘
                │
     ╔══════════▼══════════════════╗
     ║  ⑤ Optimistic ↔ ⑥ Pessimistic  ║  正反方 2 轮对抗辩论
     ║  "海尔性价比最高" vs "海尔好评率最低" ║  暴露数据矛盾点
     ╚══════════┬══════════════════╝
                │
     ┌──────────▼──────────┐
     │  ⑦ Validator        │  deep_think_llm  三方一致性检查
     │  通过 → END          │  SQL结果↔图表↔报告结论
     │  驳回 → Report 修正   │  最多驳回 2 次
     └─────────────────────┘
```

### 7 个 Agent 职责

| # | Agent | 目录 | LLM | 职责 |
|---|-------|------|-----|------|
| 1 | Planner | `agent/managers/` | deep_think (T=0.3) | 拆解用户问题为执行步骤 |
| 2 | SQL Agent | `agent/analysts/` | quick_think (T=0.1) | NL→SQL→执行，错误自动重试 |
| 3 | Chart Agent | `agent/analysts/` | quick_think (T=0.1) | 数据→Plotly 图表 JSON |
| 4 | Report Agent | `agent/synthesis/` | quick_think (T=0.1) | 汇总 Markdown 分析报告 |
| 5 | Optimistic | `agent/debaters/` | quick_think (T=0.1) | 正方辩论（乐观视角解读数据） |
| 6 | Pessimistic | `agent/debaters/` | quick_think (T=0.1) | 反方辩论（风险视角审视数据） |
| 7 | Validator | `agent/managers/` | deep_think (T=0.3) | 裁判验证（一致性检查 + 通过/驳回） |

### 双 LLM 策略

| 类型 | 温度 | 最大 Token | 使用者 |
|------|:--:|:--:|------|
| quick_think_llm | 0.1 | 4096 | SQL Agent, Chart Agent, Report Agent, Optimistic, Pessimistic |
| deep_think_llm | 0.3 | 8192 | Planner, Validator |

### LangGraph 条件路由

```
SQL Agent:
  tool_calls? → tools_sql (执行) → SQL Agent (处理结果)
  sql_error + retry<2? → SQL Agent (重试)
  否则 → Msg Clear SQL → Chart Agent

辩论:
  round_count < max_debate_rounds×2? → 交替发言
  否则 → Validator

Validator:
  approved? → END
  rejected + revision<2? → Report Agent (修正)
  revision≥2? → END (强制结束)
```

---

## 🚀 快速启动

### 环境要求

- Python 3.10+
- Node.js 18+
- LLM API Key（推荐 DeepSeek，注册即送 500 万 token）

### 1. 配置

```bash
# 编辑 .env，填入 API Key
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_PROVIDER=deepseek

# 可选：阿里云 Embedding（向量记忆用）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

### 2. 安装

```bash
# 创建虚拟环境
uv venv
uv pip install -e ".[dev]"

# 生成演示数据（可选，用于快速体验）
python -m backend.dataflows.demo_data
```

### 3. 启动

```bash
# 方式1：一键启动
start.bat

# 方式2：分别启动
start_backend.bat    # 后端 → http://localhost:4433/docs
start_frontend.bat   # 前端 → http://localhost:5173

# 方式3：手动
python -m uvicorn backend.main:app --host 127.0.0.1 --port 4433 --reload
cd frontend && npm install && npm run dev
```

### 4. 使用

1. 打开 `http://localhost:5173`
2. 左侧上传 CSV 文件（或使用预置数据）
3. 输入分析问题
4. 观察 7 个 Agent 实时协作：Planner → SQL → Chart → Report → 辩论 → Validator
5. 获取带图表的分析报告

---

## 📁 项目结构

```
DataForge/
├── README.md                        # 本文件
├── pyproject.toml                   # 依赖管理 + Ruff 配置
├── .env                             # API Key 配置
│
├── start.bat                        # 一键启动（后端 + 前端）
├── start_backend.bat                # 仅启动后端
├── start_frontend.bat               # 仅启动前端
│
├── backend/                         # Python 后端 (~50 文件)
│   ├── main.py                      # FastAPI 入口 + 生命周期管理
│   │
│   ├── llm_clients/                 # LLM 客户端工厂包
│   │   ├── factory.py               # create_llm / create_quick_llm / create_deep_llm
│   │   ├── provider_keys.py         # Provider 配置 + 别名映射
│   │   └── model_catalog.py         # 模型分层目录
│   │
│   ├── agent/                       # 7 个 Agent（按角色分目录）
│   │   ├── __init__.py              # 懒加载 _EXPORTS 注册表
│   │   ├── analysts/                # 工具调用型 Agent
│   │   │   ├── sql_agent.py         #   ② NL→SQL（含结果提取 + 重试）
│   │   │   └── chart_agent.py       #   ③ 数据→Plotly JSON（含图表提取）
│   │   ├── debaters/                # 辩论型 Agent
│   │   │   ├── optimist.py          #   ⑤ 正方辩论（乐观视角）
│   │   │   └── pessimist.py         #   ⑥ 反方辩论（谨慎视角）
│   │   ├── managers/                # 决策/裁判型 Agent
│   │   │   ├── planner.py           #   ① 任务规划
│   │   │   └── validator.py         #   ⑦ 裁判验证
│   │   ├── synthesis/               # 合成型 Agent
│   │   │   └── report_agent.py      #   ④ 报告撰写
│   │   └── utils/state.py           # AgentState TypedDict 定义
│   │
│   ├── graph/                       # LangGraph 编排层
│   │   ├── __init__.py              # 懒加载导出
│   │   ├── orchestrator.py          # DataAgentGraph 主编排器（LLM创建→图执行→计时→性能数据）
│   │   ├── graph_setup.py           # GraphSetup 图构建（加节点 + 连边 + Msg Clear）
│   │   ├── conditional_logic.py     # ConditionalLogic 条件路由（4 个路由器）
│   │   └── propagation.py           # Propagator 初始状态 + 进度标签映射
│   │
│   ├── dataflows/                   # 数据层
│   │   ├── sqlite_store.py          # SQLite CRUD + 安全限制（仅SELECT/PRAGMA/WITH）
│   │   └── demo_data.py             # 演示数据生成
│   │
│   ├── memory/                      # 上下文记忆
│   │   ├── embeddings.py            # 多 Provider Embedding（阿里云→API→本地→哈希）
│   │   ├── memory_store.py          # ChromaDB 向量记忆库（单例 + 线程安全）
│   │   └── reflector.py             # 分析反思器（事后提取经验，存入记忆）
│   │
│   ├── tools/__init__.py            # Agent 工具（execute_sql + generate_chart）
│   ├── cache/adaptive.py            # 三层自适应缓存（内存 LRU → 文件 → 数据源）
│   ├── models/schemas.py            # Pydantic 数据模型
│   │
│   ├── core/                        # 核心模块
│   │   ├── config.py                # Pydantic BaseSettings（.env 自动加载）
│   │   ├── error_handler.py         # 全局异常捕获中间件
│   │   └── rate_limiter.py          # 滑动窗口限流器
│   │
│   ├── api/                         # FastAPI 路由
│   │   ├── chat.py                  # POST /api/chat — SSE 流式分析
│   │   ├── upload.py                # POST /api/upload — CSV 上传（≤50MB, ≤10万行）
│   │   └── export.py                # POST /api/export — 报告导出（MD/DOCX/HTML）
│   │
│   └── utils/                       # 工具函数
│       ├── logging_setup.py         # 日志系统（彩色控制台 + 滚动文件）
│       ├── tool_logging.py          # @log_tool_call 装饰器
│       ├── fallback.py              # with_fallback / retry_on_failure / safe_call
│       ├── text_chunker.py          # smart_truncate（句子/段落边界截断）
│       └── report_exporter.py       # 报告导出（MD/DOCX/HTML）
│
├── frontend/                        # Vue 3 前端
│   └── src/
│       ├── main.ts                  # 入口（Pinia + Router + Element Plus）
│       ├── App.vue                  # 主布局（暗色侧边栏 + 白色对话区）
│       ├── views/
│       │   └── AnalysisView.vue     # 对话视图（气泡 + Agent 步骤 + 图表 + 辩论）
│       ├── components/
│       │   ├── DataUploader.vue     # CSV 上传 + 表预览
│       │   └── ChartCard.vue        # Plotly 图表渲染
│       ├── stores/chat.ts           # Pinia 对话状态管理
│       ├── composables/useSSE.ts    # SSE 流式封装
│       ├── router/index.ts          # Vue Router
│       └── api/index.ts             # Backend API 封装
│
├── tests/                           # 测试（57 个用例）
│   ├── conftest.py                  # 共享 fixtures
│   ├── test_sqlite_store.py         # 数据层 (11 tests)
│   ├── test_tools.py                # 工具函数 (5 tests)
│   ├── test_conditional_logic.py    # 条件路由 (11 tests)
│   ├── test_propagation.py          # 状态传播 (7 tests)
│   ├── test_token_tracker.py        # Token 追踪 (9 tests)
│   ├── test_performance.py          # 性能统计 (5 tests)
│   └── test_dataflows.py            # 数据流集成 (6 tests)
│
├── data/                            # 数据文件
│   ├── 电子产品销售数据.csv          #   5000行 × 12列（有差异）
│   └── 用户评价数据.csv              #   3000行 × 10列
│
├── deploy/                          # Docker + Nginx 部署配置
├── doc/                             # 架构文档 + Agent流程 + 面试QA
├── logs/                            # 日志文件
└── pyproject.toml
```

---

## 📊 数据集说明

项目包含两个预置数据集，通过**品牌**和**分类**列可关联查询。

### 电子产品销售数据 (`电子产品销售数据.csv`)

| 属性 | 值 |
|------|------|
| 行数 | 5,000 |
| 列数 | 12 |
| 列名 | 电子产品名、价格（元）、销量（件）、时间、分类、品牌、原价（元）、折扣率（%）、评价数量、好评率（%）、发货地、保修期（月） |
| 品牌数 | 12（苹果、华为、小米、OPPO、三星、戴尔、联想、索尼、海尔、飞利浦、格力、华硕） |
| 数据特点 | 品牌间差异明显——好评率 82%-95%、折扣率 8%-28%、价格 500-12,000、保修期 12-36 月 |

### 用户评价数据 (`用户评价数据.csv`)

| 属性 | 值 |
|------|------|
| 行数 | 3,000 |
| 列数 | 10 |
| 列名 | 评价ID、品牌、分类、用户评分、评价内容长度、是否有图、购买渠道、评价日期、是否追评、有用数 |
| 品牌数 | 15（含松下、惠普、美的等额外品牌） |
| 数据特点 | 用户评分 3.7-4.0、带图率差异明显、多渠道分布 |

### 两个数据集可问的问题

**入门（验证基础功能）**
```
电子产品销售表有多少行？哪个品牌销量最高？
```
```
用户评价表共有多少条记录？平均评分是多少？
```

**单表深度分析（验证 SQL + Chart + 报告）**
```
各品牌平均好评率和折扣率有什么关系？高好评率的品牌折扣更低吗？
```
```
按价格区间分组，分析不同价位产品的销量分布规律
```
```
保修期长的品牌销量一定好吗？用数据说话
```
```
折扣率最高的品牌和好评率最高的品牌，它们的价格和销量有什么不同？
```

**跨表关联（验证 JOIN + 多维度）**
```
关联两个表，分析用户评分高的品牌在销售表中销量表现如何？
```
```
好评率和用户评分差距最大的品牌是哪个？分析可能的原因
```
```
从两个表中找出带图评价占比高的品牌，它们的销量和好评率有什么特点？
```

**综合排名（验证全流程：规划→SQL→图表→辩论→裁判）**
```
综合考虑价格、好评率、折扣率、保修期和用户评分，给所有品牌排一个性价比名次
```
```
把两个表关联起来，按品牌分析：高价格是否意味着高好评率？折扣力度大的品牌用户评分一定低吗？保修期长的品牌销量更好吗？用三组数据对比给出结论
```

---

## ✨ 技术特性

### 核心能力

| 特性 | 实现 | 说明 |
|------|------|------|
| LangGraph 编排 | StateGraph + `add_conditional_edges` | 条件路由、循环控制、状态管理 |
| Tool Calling | `llm.bind_tools()` + ToolNode | Agent 自主决定何时调用工具，ToolNode 自动执行 |
| 对抗辩论 | Optimistic ↔ Pessimistic 交替发言 | 2 轮辩论，每轮双方各发言一次，count 控制轮次 |
| 裁判验证 | Validator + `revision_count` | 检查三方一致性，最多驳回 2 次修正 |
| 上下文记忆 | ChromaDB + Reflector | 分析完成后反思学习，检索相似历史注入 prompt |
| SQL 安全限制 | 仅允许 SELECT/PRAGMA/WITH | 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE |
| SQL 自动重试 | 错误信息喂回 Agent | 表结构查错 → 反引号修正 → 最多重试 2 次 |
| SSE 流式推送 | FastAPI StreamingResponse | 每个 Agent 执行步骤实时推送到前端 |

### 工程能力

| 特性 | 实现 | 说明 |
|------|------|------|
| 多 Provider LLM | 工厂模式 | DeepSeek / Qwen / GLM / OpenAI / SiliconFlow 一键切换 |
| 多 Provider Embedding | 四级降级 | 阿里云 DashScope → OpenAI API → 本地模型 → 哈希回退 |
| 自适应缓存 | LRU + 文件 | 内存 → 文件 → 数据源 三层回退 |
| Token 用量追踪 | TokenTracker 单例 | 记录每次 LLM 调用的输入/输出 token |
| 节点性能统计 | `propagate()` 计时 | 每个节点耗时、占比、最快/最慢节点 |
| 错误恢复 | `with_fallback` + `retry_on_failure` | 降级装饰器 + 指数退避重试 |
| 智能文本截断 | `smart_truncate` | 句子→段落→硬截断三层降级 |
| 全局异常处理 | ErrorHandlerMiddleware | ValueError→400, PermissionError→403, 其他→500 |
| 速率限制 | 滑动窗口 | 默认 30次/分钟，纯内存实现 |
| Pydantic 配置 | BaseSettings | .env 自动加载 + 类型校验 |
| 代码规范 | Ruff | 自动检查 + 格式化，提交前强制运行 |
| 报告导出 | MD/DOCX/HTML | 含 SQL 查询记录 + 性能统计 |

---

## 🔧 LLM 配置

编辑 `.env` 文件：

```env
# DeepSeek（推荐，国内直连，性价比最高）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_PROVIDER=deepseek

# 阿里云 Embedding（向量记忆用，可选）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# 阿里百炼
# LLM_PROVIDER=qwen
# DASHSCOPE_API_KEY=sk-xxx

# 智谱 GLM
# LLM_PROVIDER=glm
# ZHIPU_API_KEY=xxx
```

| Provider | 默认模型 | 推荐场景 |
|----------|---------|---------|
| DeepSeek | deepseek-chat | 性价比最高，国内直连 |
| 阿里百炼 | qwen-plus | 中文优化，Embedding 首选 |
| 智谱 GLM | glm-4-flash | 国产替代 |
| OpenAI | gpt-4o-mini | 需海外网络 |
| SiliconFlow | Qwen2.5-7B | 开源模型托管 |

---

## 🚀 启动脚本

| 脚本 | 功能 | 说明 |
|------|------|------|
| `start.bat` | 一键启动 | 自动清理旧数据库、启动后端 + 前端 |
| `start_backend.bat` | 仅后端 | 端口 4433 |
| `start_frontend.bat` | 仅前端 | 端口 5173，自动 `npm install` |

启动时自动：
- 检测 Python/Node 环境
- 清理旧 SQLite 数据库
- 导入 `data/` 下所有 CSV 到 SQLite
- 创建 UV venv（如存在）或使用系统 Python
- 首次启动自动安装前端依赖

---

## 🧪 测试

### 运行测试

```bash
# 全部测试
python -m pytest tests/ -v

# 按模块
python -m pytest tests/test_sqlite_store.py -v
python -m pytest tests/test_token_tracker.py -v
python -m pytest tests/test_conditional_logic.py -v
```

### 测试结果

```
============================= 57 passed in 25.87s =============================

tests/test_conditional_logic.py  (11 tests)    条件路由：SQL重试、辩论轮次、Validator驳回
tests/test_dataflows.py          (6 tests)     CSV导入+查询+错误处理
tests/test_performance.py        (5 tests)     性能统计：节点计时、百分比、全流程模拟
tests/test_propagation.py        (7 tests)     状态传播：初始状态、历史上下文、进度映射
tests/test_sqlite_store.py       (11 tests)    数据层：CRUD、安全限制、PRAGMA、CTE、注释剥离
tests/test_token_tracker.py      (9 tests)     Token追踪：记录、快照、重置、线程安全、单例
tests/test_tools.py              (5 tests)     工具函数：SQL执行、图表生成
```

### 代码规范

```bash
# 提交前运行
python -m ruff check backend/ tests/    # 代码检查
python -m ruff format backend/ tests/   # 代码格式化
```

---

## 🎤 面试问答

| 问题 | 回答要点 |
|------|---------|
| 为什么用 LangGraph？ | 条件路由（SQL失败重试、无数据跳过图表）+ 辩论循环 + Validator 驳回修正，纯链式做不到 |
| 为什么 7 个 Agent？ | 关注点分离——每个 Agent prompt 短且精准。辩论防止确认偏误，裁判保证质量 |
| 辩论机制的价值？ | 正反方对抗讨论暴露数据矛盾点，类似学术 peer review |
| SQL 写错了怎么办？ | 错误信息喂回 Agent → LLM 分析原因 → 自动修正重试，最多 2 次 |
| Validator 怎么判断？ | 检查三方一致性：SQL 结果 ↔ 图表数据 ↔ 报告结论 |
| 上下文记忆怎么工作？ | ChromaDB 向量存储，分析完成后 Reflector 提取经验，下次检索相似历史 |
| Embedding 不可用怎么办？ | 四级降级：阿里云 → OpenAI API → 本地模型 → 哈希回退，保证永不崩溃 |
| Token 用量怎么追踪？ | TokenTracker 单例，每次 LLM 调用自动记录 input/output token |
| 怎么保证 SQL 不被滥用？ | 白名单机制：仅允许 SELECT/PRAGMA/WITH，禁止 INSERT/UPDATE/DELETE/DROP |
| 为什么用 SSE 而不是 WebSocket？ | 单向推送足够，比 WebSocket 更轻量，Nginx 配置简单 |
| 缓存怎么设计的？ | 三层回退：内存 LRU → 文件持久化 → 原始数据源，任何一层失败自动降级 |
| 项目架构参考了什么？ | 研究了 TradingAgents-CN 的 LangGraph 编排模式（Agent 工厂、条件路由、辩论机制），独立迁移到通用数据分析场景 |

---

## ⚠️ 声明

本项目仅供**学习研究**使用。AI 生成的分析结论基于上传数据的统计特征，不构成任何商业决策建议。
