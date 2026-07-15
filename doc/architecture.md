# DataForge AI 架构文档

## 技术选型

| 层 | 技术 | 选型理由 |
|----|------|---------|
| Agent 编排 | LangGraph >=0.4.8 | 有状态图编排，条件路由 + 循环控制，原生 ToolNode |
| LLM 接入 | ChatOpenAI (langchain-openai) | 统一 OpenAI 兼容接口，覆盖 5 家 Provider |
| 后端 | FastAPI + uvicorn >=0.104 | 异步高性能，自动 OpenAPI 文档，原生 SSE |
| 前端 | Vue 3 + Vite + Pinia | 组合式 API，状态管理，SPA |
| UI 库 | Element Plus >=2.8 | 成熟企业级组件库 |
| 图表 | Plotly.js >=2.35 | 服务端生成 JSON，前端渲染，交互式图表 |
| 向量库 | ChromaDB >=0.5 | 本地持久化，零配置，Python 内嵌 |
| Embedding | 阿里云 DashScope / OpenAI 兼容 | text-embedding-v3，中文最优 |
| 数据库 | SQLite (内置) | 零配置，面试现场一键启动 |
| 缓存 | 自研 AdaptiveCache | 无外部依赖，LRU 内存 + 文件 |
| 代码质量 | Ruff >=0.11 | Rust 实现，毫秒级检查 + 格式化 |
| CI/CD | GitHub Actions | push/PR → lint + test + build (Python 3.10-3.12) |
| 前端测试 | Vitest | Vite 原生，零配置，jsdom 环境 |

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                  Vue 3 前端 (Port 5173)               │
│  Pinia Store → useSSE Composable → Design Tokens     │
│  Vitest (17 tests) + Plotly Charts + Markdown Render │
└──────────────────────┬───────────────────────────────┘
                       │ SSE / HTTP
┌──────────────────────┴───────────────────────────────┐
│               FastAPI 后端 (Port 4433)                │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │ API: /chat (SSE)  /upload (CSV)  /export (DOCX)│ │
│  │ Auth: X-API-Key 鉴权中间件（开发模式自动跳过）  │ │
│  └────────────────────┬────────────────────────────┘ │
│                       │                               │
│  ┌────────────────────▼────────────────────────────┐ │
│  │          DataAgentGraph (主编排器)               │ │
│  │  Config(Pydantic) + Propagator + Reflector      │ │
│  │  + TokenTracker + ConditionalLogic              │ │
│  │  + DebateScorer + EvalRunner                    │ │
│  └────────────────────┬────────────────────────────┘ │
│                       │                               │
│  ┌────────────────────▼────────────────────────────┐ │
│  │           LangGraph StateGraph                   │ │
│  │                                                  │ │
│  │  START → Planner → SQL Agent ⇄ tools_sql        │ │
│  │     → Msg Clear → Chart Agent ⇄ tools_chart     │ │
│  │     → Msg Clear → Report Agent                  │ │
│  │     → Optimistic ⇄ Pessimistic (Debate)         │ │
│  │     → Validator → END / Report Agent (驳回)      │ │
│  └────────────────────┬────────────────────────────┘ │
│                       │                               │
│  ┌────────────────────▼────────────────────────────┐ │
│  │   Services: Tools(SQL/Chart) + Memory(ChromaDB) │ │
│  │   + Cache(LRU+File) + Core(Config/Auth/RateLim) │ │
│  │   + Eval(Metrics+Runner) + Debate Scorer        │ │
│  └────────────────────┬────────────────────────────┘ │
│                       │                               │
│  ┌────────────────────▼────────────────────────────┐ │
│  │   Data: SQLiteStore + DemoData + CSV Upload     │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

## 目录结构

```
backend/
├── main.py                     # FastAPI 入口，lifespan 生命周期
├── llm_clients/                # LLM 工厂包
│   ├── factory.py              # create_llm / create_quick_llm / create_deep_llm
│   ├── provider_keys.py        # Provider 配置表 + 别名 + 标准化
│   └── model_catalog.py        # 模型分层目录
├── prompts/                    # Prompt 模板（9 个 Markdown 文件）
│   ├── __init__.py             # load_prompt() 加载器
│   ├── planner.md              # ① 任务规划
│   ├── sql_agent.md            # ② SQL 生成
│   ├── chart_agent.md          # ③ 图表生成
│   ├── report_agent.md         # ④ 报告撰写
│   ├── optimist.md             # ⑤ 正方辩论
│   ├── pessimist.md            # ⑥ 反方辩论
│   ├── validator.md            # ⑦ 裁判验证
│   └── debate_scorer.md        # 辩论评分器
├── agent/                      # 7 个 Agent（按角色分目录）
│   ├── __init__.py             # _EXPORTS 懒加载
│   ├── analysts/               # SQL Agent, Chart Agent（工具调用型）
│   ├── debaters/               # Optimistic, Pessimistic, Scorer（辩论+评分）
│   ├── managers/               # Planner, Validator（决策/裁判型）
│   ├── synthesis/              # Report Agent（合成型）
│   └── utils/state.py          # AgentState (TypedDict)
├── eval/                       # 质量评估框架
│   ├── __init__.py             # 评估 API 导出
│   ├── metrics.py              # 多维度评分指标（SQL/Chart/Report/Debate）
│   └── runner.py               # 批量评估用例运行 + Markdown 报告
├── graph/                      # LangGraph 编排
│   ├── orchestrator.py         # DataAgentGraph 主编排器
│   ├── graph_setup.py          # GraphSetup 图构建
│   ├── conditional_logic.py    # 条件路由（4 个路由器）
│   └── propagation.py          # 初始状态 + 进度标签
├── dataflows/                  # 数据层
│   ├── sqlite_store.py         # SQLite 管理（仅 SELECT）
│   └── demo_data.py            # 演示数据生成
├── memory/                     # 上下文记忆
│   ├── embeddings.py           # 多 Provider Embedding 降级
│   ├── memory_store.py         # ChromaDB 向量存储
│   └── reflector.py            # 分析反思器
├── tools/                      # Agent 工具（@tool 装饰器）
├── cache/adaptive.py           # 三层自适应缓存
├── models/schemas.py           # Pydantic 数据模型
├── core/                       # 配置 + 鉴权 + 错误处理 + 限流
│   ├── config.py               # Pydantic BaseSettings
│   ├── auth.py                 # API Key 鉴权中间件
│   ├── error_handler.py        # 全局异常捕获
│   └── rate_limiter.py         # 滑动窗口限流器
├── api/                        # chat(SSE) + upload(CSV) + export(DOCX)
└── utils/                      # 日志 + 降级 + 截断 + JSON解析 + 导出

frontend/
└── src/
    ├── main.ts                 # Pinia + Router + Element Plus
    ├── App.vue                 # 暗色侧边栏 + 对话区布局
    ├── env.d.ts                # TypeScript 类型声明（Plotly）
    ├── views/AnalysisView.vue  # 对话视图（气泡/步骤/图表/辩论）
    ├── components/
    │   ├── DataUploader.vue    # CSV 上传 + 表预览
    │   └── ChartCard.vue       # Plotly 图表渲染
    ├── stores/chat.ts          # Pinia 对话状态（SSE事件路由）
    ├── composables/useSSE.ts   # SSE 流式封装
    ├── styles/tokens.css       # Design Tokens（CSS 变量体系）
    └── __tests__/chat.test.ts  # 前端单元测试（17个）
```

## 双 LLM 策略

| 类型 | 温度 | Token | 使用者 | 原因 |
|------|:--:|:--:|------|------|
| quick_think | 0.1 | 4096 | SQL/Chart/Report/Optimistic/Pessimistic | 工具调用需精确 |
| deep_think | 0.3 | 8192 | Planner/Validator | 规划裁判需全面 |

## 辩论评分体系

辩论结束后，`DebateScorer` 独立调用 LLM 对正反方从三个维度量化评分：

| 维度 | 权重 | 评估要点 |
|------|:--:|------|
| 论据质量 | 40% | 逻辑是否严密、因果关系推断是否合理 |
| 数据支撑 | 40% | 引用的数据是否与 SQL 结果一致、解读是否合理 |
| 反驳力度 | 20% | 是否有效回应对手核心论点，是否揭露对方数据盲区 |

评分结果通过 SSE 推送到前端，以可视化对比卡片展示。

## 质量评估框架

`backend/eval/` 实现了多维度的 Agent 输出质量自动评分：

| Agent | 评估指标 |
|-------|---------|
| SQL Agent | 语法正确性(30%) + 结果非空(30%) + 错误恢复(20%) + ReAct效率(20%) |
| Chart Agent | 图表生成率(50%) + 数据适配性(30%) + 迭代效率(20%) |
| Report Agent | 字数(25%) + 无幻觉(35%) + 结构完整性(25%) + 数据引用(15%) |
| 辩论 | 双方参与(30%) + 反驳质量(30%) + 数据支撑(25%) + 评分可用(15%) |

每次分析完成后自动运行评估，综合分数通过 SSE 推送到前端。

## Embedding 降级

```
阿里云 DashScope (text-embedding-v3, 1024维)
  → OpenAI 兼容 API (text-embedding-3-small)
    → 本地 sentence-transformers (all-MiniLM-L6-v2, 384维)
      → SHA256 哈希回退 (保证不崩溃)
```

## 安全机制

| 机制 | 实现 |
|------|------|
| SQL 安全 | 仅允许 SELECT，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE |
| API Key 鉴权 | X-API-Key Header / ?api_key Query，常量时间比较防时序攻击 |
| 速率限制 | 滑动窗口，默认 30次/分钟 |
| 异常捕获 | ErrorHandlerMiddleware，按类型返回标准化错误 |
| 死循环防护 | SQL重试≤2, Agent迭代≤5, 辩论轮次≤max×2, 驳回修订≤2, 递归≤50 |
