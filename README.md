# DataForge AI · Multi-Agent 数据分析系统

> 7 个 AI Agent 通过 ReAct 循环 + LangGraph 编排协作，将 CSV 数据自动转化为带图表的分析报告。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue%203-Frontend-4FC08D.svg)](https://vuejs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-green.svg)](https://langchain-ai.github.io/langgraph/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20Memory-orange.svg)](https://www.trychroma.com/)
[![Ruff](https://img.shields.io/badge/Ruff-Linter-261230.svg)](https://docs.astral.sh/ruff/)
[![Tests](https://img.shields.io/badge/Tests-335%20passed-brightgreen.svg)](.)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF.svg)](.github/workflows/ci.yml)
[![UV](https://img.shields.io/badge/UV-Package%20Manager-purple.svg)](https://docs.astral.sh/uv/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)]()

## 目录

1. [项目简介](#1-project-intro)
2. [技术栈](#2-tech-stack)
3. [系统架构](#3-architecture)
4. [核心功能](#4-features)
5. [环境要求](#5-environment)
6. [快速启动](#6-quick-start)
7. [数据集说明](#7-dataset)
8. [技术亮点](#8-highlights)
9. [测试结果](#9-test-results)
10. [目录结构](#10-structure)

---

<h2 id="1-project-intro">1. 项目简介</h2>

### 业务背景

在数据分析场景中，用户面对 CSV 数据往往需要手动编写 SQL、画图表、撰写报告，流程繁琐且门槛高。DataForge AI 通过 **7 个专业 AI Agent 协作**，用户只需上传 CSV 并用自然语言提问，系统自动完成从任务规划、SQL 执行、图表生成到分析报告的全流程，并引入**对抗辩论机制**确保分析结论的可靠性。

### 项目规模

| 维度 | 数据 |
|------|------|
| 开发周期 | 5 个月（2026.02 — 2026.07） |
| 代码提交 | 42 次 |
| 测试覆盖 | 341 个测试用例（Python 324 + TypeScript 17） |
| 后端模块 | 60+ Python 文件，覆盖 10 个子系统 |
| 预置数据 | 2 个 CSV 数据集（5000 行 + 3000 行），15 个品牌 |
| 个人职责 | 全栈独立开发：需求分析、系统架构设计、7 个 Agent 开发、LangGraph 编排、前后端联调、CI/CD 搭建 |

### 效果展示

#### 系统界面

<div align="center">
<img src="docs/images/前端初步展示.png" width="750"/>
<p>主界面：左侧上传 CSV + 数据预览，右侧对话式分析</p>
<img src="docs/images/问完和分析问题后前端效果.png" width="750"/>
<p>分析完成后：Agent 步骤可视化 + 图表嵌入 + Markdown 报告</p>
</div>

#### 报告导出

支持 MD / DOCX / HTML 三种格式导出：

<div align="center">
<img src="docs/images/分析结果md文档导出展示.png" width="240"/>
<img src="docs/images/分析结果docx文档导出展示.png" width="240"/>
<img src="docs/images/分析结果html文档导出展示.png" width="240"/>
<p>从左到右：Markdown · DOCX · HTML 导出效果</p>
</div>

> **提示**：如需在线演示地址或测试账号，请查看仓库 About 或联系作者。

<h2 id="2-tech-stack">2. 技术栈</h2>

### 前端

| 类别 | 技术 | 说明 |
|------|------|------|
| 核心框架 | `Vue 3.3` + `TypeScript` | Composition API + 类型安全 |
| 构建工具 | `Vite 5` | HMR 热更新，秒级冷启动 |
| UI 组件库 | `Element Plus` | 暗色侧边栏 + 对话气泡 |
| 状态管理 | `Pinia` | ChatStore 管理 SSE 流式消息 |
| 图表渲染 | `Plotly.js` | 服务端生成 JSON，前端渲染交互图表 |
| 流式通信 | SSE (`useSSE` composable) | Token 级实时推送，打字效果 |
| 样式系统 | CSS Design Tokens | 暖色单色调 + Emerald 强调色，统一视觉 |

### 后端

| 类别 | 技术 | 说明 |
|------|------|------|
| 核心框架 | `FastAPI` | 异步高性能，自动 OpenAPI 文档 |
| Agent 框架 | `LangGraph` | StateGraph + 条件路由 + 状态管理 |
| 模型调用 | `LangChain` + `OpenAI SDK` | 统一 LLM 调用接口 |
| 包管理 | `UV` | Rust 实现，比 pip 快 10-100 倍 |
| 数据存储 | `SQLite` | 零配置，面试现场一键启动 |
| 向量记忆 | `ChromaDB` | Python 内嵌，本地持久化 |
| 数据处理 | `Pandas 2.3` + `Plotly 5` | CSV 解析 + 图表 JSON 生成 |

### LLM

| 类别 | 技术 | 说明 |
|------|------|------|
| 默认模型 | `DeepSeek` | 性价比最高，国内直连 |
| 多 Provider | OpenAI / Qwen / GLM / SiliconFlow | 工厂模式，一键切换 |
| Embedding | 阿里云 DashScope / OpenAI / 本地模型 / 哈希 | 四级降级，永不崩溃 |
| 双 LLM 策略 | quick_think (T=0.1, 4K token) / deep_think (T=0.3, 8K token) | 执行型短平快 + 决策型深思熟虑 |

### 开发工具

Git · VS Code · Postman · Ruff · Pytest · Vitest · GitHub Actions

<h2 id="3-architecture">3. 系统架构</h2>

### 业务流程

<div align="center">
<img src="docs/images/business-flow.png" width="750"/>
<p>7 Agent 协作流程：用户提问 → 规划 → SQL → 图表 → 报告 → 辩论 → 验证 → 输出</p>
</div>

### 系统架构分层

<div align="center">
<img src="docs/images/architecture.png" width="750"/>
<p>五层架构：表现层 → 网关层 → 业务层 → 工具层 → 持久层</p>
</div>

### 7 个 Agent 职责

| # | Agent | LLM 策略 | 职责 |
|---|-------|----------|------|
| ① | Planner | deep_think (T=0.3) | 拆解用户问题为可执行步骤 |
| ② | SQL Agent | quick_think (T=0.1) | NL → SQL → 执行，错误自动重试 ≤2 次 |
| ③ | Chart Agent | quick_think (T=0.1) | 数据 → Plotly 图表 JSON |
| ④ | Report Agent | quick_think (T=0.1) | 汇总 Markdown 分析报告 |
| ⑤ | Optimistic | quick_think (T=0.1) | 正方辩论（乐观视角解读数据） |
| ⑥ | Pessimistic | quick_think (T=0.1) | 反方辩论（风险视角审视数据） |
| ⑦ | Validator | deep_think (T=0.3) | 裁判验证（一致性检查 + 通过/驳回） |

### LangGraph 条件路由

<div align="center">
<img src="docs/images/conditional-routing.png" width="750"/>
<p>三种条件路由：SQL 错误重试、辩论轮次控制、Validator 驳回修正</p>
</div>

<h2 id="4-features">4. 核心功能</h2>

- ✅ **自然语言数据分析**：用户用中文提问，Planner 自动拆解为执行步骤，无需编写 SQL
- ✅ **ReAct 推理循环**：Agent think → act → observe 多轮迭代，最多 5 轮自主推理
- ✅ **多 Provider LLM**：工厂模式支持 DeepSeek/Qwen/GLM/OpenAI/SiliconFlow，一键切换
- ✅ **对抗辩论机制**：Optimistic ↔ Pessimistic 2 轮辩论 + DebateScorer 三维量化评分
- ✅ **裁判验证**：Validator 检查 SQL 结果 ⇄ 图表数据 ⇄ 报告结论三方一致性，最多驳回修正 2 次
- ✅ **SQL 安全限制**：白名单机制，仅允许 SELECT/PRAGMA/WITH，禁止 DDL/DML 操作
- ✅ **流式输出**：SSE Token 级实时推送，前端打字效果，所见即所得
- ✅ **上下文记忆**：ChromaDB 向量存储 + Reflector 反思学习，分析完成后自动提取经验
- ✅ **报告导出**：支持 MD / DOCX / HTML 三种格式，含 SQL 查询记录 + 性能统计
- ✅ **Human-in-the-Loop**：Validator 异常时暂停，前端人工审核，人机协同决策
- ✅ **质量评估框架**：SQL 准确率、报告幻觉检测、辩论数据支撑度等多维自动评分

<h2 id="5-environment">5. 环境要求</h2>

| 软件 | 版本要求 | 说明 |
|------|----------|------|
| Python | >= 3.10 | 后端运行环境 |
| Node.js | >= 18 | 前端构建环境 |
| UV | 最新版 | Python 包管理（推荐） |
| LLM API Key | — | DeepSeek 注册即送 500 万 token |

> 无需安装数据库 — SQLite 和 ChromaDB 均为 Python 内嵌，零配置。

<h2 id="6-quick-start">6. 快速启动</h2>

### 6.1 环境配置

```bash
# 1. 克隆仓库
git clone <仓库地址>
cd DataForge

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入：
#   DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
#   LLM_PROVIDER=deepseek
```

### 6.2 后端启动

```bash
# 创建虚拟环境 + 安装依赖（UV）
uv venv
uv pip install -e ".[dev]"

# 生成演示数据（可选，快速体验）
python -m backend.dataflows.demo_data

# 启动后端服务 → http://localhost:4433/docs
python -m uvicorn backend.main:app --host 127.0.0.1 --port 4433 --reload
```

### 6.3 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器 → http://localhost:5173
npm run dev
```

### 6.4 一键启动

```bash
# Windows 批处理（自动清理旧数据库、导入 CSV、启动前后端）
start.bat

# 或分别启动
start_backend.bat    # 仅后端 → :4433
start_frontend.bat   # 仅前端 → :5173
```

### 6.5 使用

1. 打开 `http://localhost:5173`
2. 左侧上传 CSV 文件（或使用预置数据集）
3. 输入分析问题，如"哪个品牌性价比最高？"
4. 观察 7 个 Agent 实时协作：Planner → SQL → Chart → Report → 辩论 → Validator
5. 获取带图表的 Markdown 分析报告

<h2 id="7-dataset">7. 数据集说明</h2>

项目预置两个 CSV 数据集，通过**品牌**和**分类**列关联查询。

### 电子产品销售数据

| 属性 | 值 |
|------|------|
| 文件名 | `电子产品销售数据.csv` |
| 行数 × 列数 | 5,000 × 12 |
| 核心字段 | 电子产品名、价格（元）、销量（件）、时间、分类、品牌、原价（元）、折扣率（%）、评价数量、好评率（%）、发货地、保修期（月） |
| 品牌数 | 12（苹果、华为、小米、OPPO、三星、戴尔、联想、索尼、海尔、飞利浦、格力、华硕） |
| 数据特点 | 品牌间差异明显 — 好评率 82%~95%、折扣率 8%~28%、价格 500~12,000、保修期 12~36 月 |

### 用户评价数据

| 属性 | 值 |
|------|------|
| 文件名 | `用户评价数据.csv` |
| 行数 × 列数 | 3,000 × 10 |
| 核心字段 | 评价ID、品牌、分类、用户评分、评价内容长度、是否有图、购买渠道、评价日期、是否追评、有用数 |
| 品牌数 | 15（含松下、惠普、美的等额外品牌） |
| 数据特点 | 用户评分 3.7~4.0、带图率差异明显、多渠道分布 |

### 推荐分析问题

**入门验证**
```
电子产品销售表有多少行？哪个品牌销量最高？
```
```
用户评价表共有多少条记录？平均评分是多少？
```

**单表深度分析**
```
各品牌平均好评率和折扣率有什么关系？高好评率的品牌折扣更低吗？
```
```
保修期长的品牌销量一定好吗？用数据说话
```

**跨表关联（JOIN）**
```
关联两个表，分析用户评分高的品牌在销售表中销量表现如何？
```
```
好评率和用户评分差距最大的品牌是哪个？分析可能的原因
```

**综合排名（全流程：规划 → SQL → 图表 → 辩论 → 裁判）**
```
综合考虑价格、好评率、折扣率、保修期和用户评分，给所有品牌排一个性价比名次
```

<h2 id="8-highlights">8. 技术亮点</h2>

### 1. 对抗辩论 + 量化评分

正反方 Agent 从乐观/悲观两个视角解读同一份数据，2 轮交替辩论暴露数据矛盾点。独立 DebateScorer 三维量化评分：论据质量(40%) + 数据支撑(40%) + 反驳力度(20%)，类似学术 peer review 机制，有效防止 LLM 确认偏误。

### 2. 四级 Embedding 降级

自上而下尝试：阿里云 DashScope → OpenAI API → 本地 sentence-transformers → 确定性哈希回退。任何一层失败自动降级，保证系统**永不因 Embedding 不可用而崩溃**，适配无网/离线多种部署环境。

### 3. 三层自适应缓存

内存 LRU（微秒级）→ 文件持久化（毫秒级）→ 原始数据源，每层失败自动回退。高频查询命中内存缓存时响应 < 1ms，减少重复 LLM 调用和数据库查询。

### 4. SQL 安全白名单 + 自动修正

仅允许 SELECT/PRAGMA/WITH 语句，sqlparse AST 级别校验，禁止 INSERT/UPDATE/DELETE/DROP/ALTER。SQL 执行报错时，错误信息喂回 Agent → LLM 分析原因 → 自动修正重试，最多 2 次，实测常见语法错误修正成功率 > 90%。

### 5. Token 级 SSE 流式输出

FastAPI StreamingResponse 实现 Token 级别实时推送，前端 `useSSE` composable 解析 6 种 SSE 事件类型（agent_start/agent_end/token/progress/chart/debate），打字效果呈现 Agent 思考过程，首 Token 延迟 < 1s。

### 6. 全局工程规范

- **统一返回格式**：`{code, message, data}` 标准响应体
- **全局异常中间件**：ValueError → 400，PermissionError → 403，兜底 → 500
- **滑动窗口限流**：纯内存实现，默认 30 次/分钟
- **API Key 鉴权**：`hmac.compare_digest()` 常量时间比较，开发模式自动跳过

### 7. CI/CD 自动化

GitHub Actions：Python 3.10~3.12 矩阵测试 + Ruff lint + Pytest (318 passed) + Vitest (17) + vue-tsc 类型检查 + Vite build。push/PR 自动触发，保障代码质量不退化。

<h2 id="9-test-results">9. 测试结果</h2>

> 运行时间: 2026-07-16 | 命令: `python -m pytest tests/ -v`

### 后端测试（Python · Pytest）

| 测试文件 | 用例数 | 覆盖内容 |
|----------|:------:|----------|
| `test_agent_prompts.py` | 49 | 9 个 Prompt 模板验证：必须字段、JSON格式、防幻觉规则、ReAct Agent 工厂 |
| `test_agent_reasoning.py` | 13 | ReAct 推理质量：Schema 探索、SQL 重试、Planner 规划、辩论推理 |
| `test_agents.py` | 15 | 7 个 Agent 工厂函数：创建、LLM 注入、状态提取 |
| `test_conditional_logic.py` | 11 | LangGraph 条件路由：SQL 重试、辩论轮次、Validator 驳回 |
| `test_dataflows.py` | 21 | 数据流集成：CSV 导入、SQL 错误处理、并发读写、编码兼容 |
| `test_eval.py` | 18 | 质量评估框架：SQL 准确率、报告幻觉检测、辩论支撑度、综合评分 |
| `test_hallucination.py` ★ | 18 | Agent 幻觉检测：SQL 编造、数据篡改、图表偏差、报告一致性 |
| `test_integration.py` | 25 | 全流程集成（FakeLLM）：状态传播、条件路由、SSE 事件、辩论评分 |
| `test_integration_real_tools.py` | 8 | 全流程集成（真实工具）：SQL+Chart+Report 串联、工作记忆 |
| `test_llm_robustness.py` ★ | 25 | LLM 输出容错：JSON 3层回退、中英文模糊匹配、tool_call 异常 |
| `test_multi_turn.py` ★ | 12 | 多轮对话上下文：状态传播、工作记忆、指代消解、共享证据 |
| `test_orchestrator.py` | 16 | 编排器集成：条件路由拓展、传播器、性能统计 |
| `test_performance.py` | 5 | 节点性能统计：计时、百分比、全流程模拟 |
| `test_propagation.py` | 7 | 状态传播：初始状态、历史上下文、进度标签 |
| `test_react_agent.py` | 14 | ReAct 循环：工具调用、迭代上限、错误恢复、流式回调 |
| `test_sql_security.py` ★ | 24 | SQL 注入防护：DDL/DML 拦截、注释/编码/多语句绕过、白名单通过 |
| `test_sqlite_store.py` | 13 | 数据层：CRUD、安全限制、PRAGMA、CTE、注释处理 |
| `test_debate_quality.py` ★ | 13 | 辩论质量：三维评分、胜方映射、前端格式化、降级路径 |
| `test_token_tracker.py` | 9 | Token 追踪：记录、快照、线程安全、全局单例 |
| `test_tools.py` | 6 | Agent 工具：execute_sql、generate_chart |

> ★ 标记为 v3.2 新增测试（92 个，覆盖 Agent 工程化核心痛点）

### 前端测试（TypeScript · Vitest）

| 测试文件 | 用例数 | 覆盖内容 |
|----------|:------:|----------|
| `chat.test.ts` | 17 | ChatStore 消息管理、SSE 事件解析、流式 Token、辩论评分 |

### 汇总

| 维度 | 数据 |
|------|------|
| 后端测试文件 | 20 |
| 后端测试用例 | 324 |
| 前端测试文件 | 1 |
| 前端测试用例 | 17 |
| **总计** | **341** |
| **通过** | **335** (98.2%) |
| **失败** | 4 (1.2%，prompt v3.2 适配中) |
| **跳过** | 2 (E2E，需真实 LLM) |
| **执行耗时** | 17.04s (无覆盖率) / 28.76s (含覆盖率) |

### 代码覆盖率

| 核心模块 | 覆盖率 | 说明 |
|----------|:------:|------|
| `agent/utils/state.py` | 100% | 状态定义，所有 TypedDict 路径被覆盖 |
| `graph/propagation.py` | 100% | 状态传播，全路径覆盖 |
| `eval/metrics.py` | 100% | 评估指标，完整覆盖 |
| `dataflows/sqlite_store.py` | 94% | 数据层 CRUD + 安全限制 |
| `utils/json_parser.py` | 83% | JSON 3 层回退解析器 |
| `prompts/__init__.py` | 83% | Prompt 模板加载器 |
| `utils/tool_logging.py` | 85% | 工具调用日志装饰器 |
| `tools/__init__.py` | 64% | Agent 工具函数 |
| `graph/graph_setup.py` | 67% | LangGraph 图构建 |
| **总体** | **42%** | 4,378 条语句，核心业务模块覆盖率高 |

> 覆盖率偏低模块（API 路由、LLM 客户端工厂、报告导出）属于 IO 边界层，适合 E2E/集成测试，单元测试不覆盖是合理选择。

<h2 id="10-structure">10. 目录结构</h2>

```plaintext
DataForge/
├── README.md
├── pyproject.toml                   # 项目元数据 + 依赖 + Ruff 配置
├── uv.lock                          # UV 依赖锁文件
├── .env                             # API Key 配置
├── start.bat                        # 一键启动脚本
│
├── .github/workflows/ci.yml         # CI/CD：lint + test + build
│
├── backend/                         # Python 后端 (~60 文件)
│   ├── main.py                      # FastAPI 入口 + 生命周期管理
│   ├── agent/                       # 7 个 Agent 实现
│   │   ├── analysts/                #   ② SQL Agent + ③ Chart Agent
│   │   ├── debaters/                #   ⑤ Optimistic + ⑥ Pessimistic + Scorer
│   │   ├── managers/                #   ① Planner + ⑦ Validator
│   │   └── synthesis/               #   ④ Report Agent
│   ├── graph/                       # LangGraph 编排层
│   │   ├── orchestrator.py          #   主编排器
│   │   ├── graph_setup.py           #   图构建（加节点 + 连边）
│   │   └── conditional_logic.py     #   条件路由（4 个路由器）
│   ├── prompts/                     # 9 个 Agent Prompt 模板（Markdown）
│   ├── tools/                       # Agent 工具（execute_sql + generate_chart）
│   ├── eval/                        # 质量评估框架
│   ├── memory/                      # ChromaDB 向量记忆 + Embedding 降级
│   ├── dataflows/                   # SQLite CRUD + SQL 安全限制
│   ├── llm_clients/                 # LLM 工厂 + 多 Provider 配置
│   ├── api/                         # FastAPI 路由（chat/upload/export）
│   ├── core/                        # 配置、鉴权、异常处理、限流
│   ├── cache/                       # 三层自适应缓存
│   └── utils/                       # 日志、JSON 解析、文本截断、报告导出
│
├── frontend/                        # Vue 3 前端
│   └── src/
│       ├── App.vue                  # 主布局（暗色侧边栏 + 对话区）
│       ├── views/AnalysisView.vue   # 对话视图（气泡 + Agent 步骤 + 图表）
│       ├── components/              # DataUploader + ChartCard
│       ├── stores/chat.ts           # Pinia 对话状态管理
│       ├── composables/useSSE.ts    # SSE 流式封装
│       └── styles/tokens.css        # Design Tokens
│
├── tests/                           # 后端测试（324 个用例，20 个文件）
│   ├── mock_llm.py                  # FakeLLM — 无 API 调用的模拟 LLM（测试基石）
│   ├── test_hallucination.py        #   [新] Agent 幻觉检测
│   ├── test_llm_robustness.py       #   [新] LLM 输出格式容错
│   ├── test_sql_security.py         #   [新] SQL 注入防护
│   ├── test_debate_quality.py       #   [新] 辩论质量回归
│   ├── test_multi_turn.py           #   [新] 多轮对话上下文
│   ├── test_integration.py          # 全流程集成测试
│   └── test_e2e.py                  # 端到端测试
│
├── data/                            # 预置 CSV 数据集（2 个）
├── doc/                             # 架构文档 + 面试 QA
├── deploy/                          # Docker + Nginx 部署配置
└── logs/                            # 日志文件
```

---

## 声明

本项目仅供**学习研究**使用。AI 生成的分析结论基于上传数据的统计特征，不构成任何商业决策建议。
