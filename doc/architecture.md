# DataForge AI 架构文档

## 技术选型

| 层 | 技术 | 选型理由 |
|----|------|---------|
| Agent 编排 | LangGraph >=0.4.8 | 有状态图编排，条件路由 + 循环控制，原生 ToolNode |
| LLM 接入 | ChatOpenAI (langchain-openai) | 统一 OpenAI 兼容接口，覆盖 5 家 Provider |
| 后端 | FastAPI + uvicorn >=0.104 | 异步高性能，自动 OpenAPI 文档，原生 SSE |
| 前端 | Vue 3 + Vite + Pinia | 组合式 API，状态管理，SPA |
| UI 库 | Element Plus >=2.8 | 成熟企业级组件库 |
| 向量库 | ChromaDB >=0.5 | 本地持久化，零配置，Python 内嵌 |
| Embedding | 阿里云 DashScope / OpenAI 兼容 | text-embedding-v3，中文最优 |
| 数据库 | SQLite (内置) | 零配置，面试现场一键启动 |
| 缓存 | 自研 AdaptiveCache | 无外部依赖，LRU 内存 + 文件 |
| 代码质量 | Ruff >=0.11 | Rust 实现，毫秒级检查 + 格式化 |

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                  Vue 3 前端 (Port 5173)               │
│  Pinia Store → useSSE Composable → Element Plus UI   │
└──────────────────────┬───────────────────────────────┘
                       │ SSE / HTTP
┌──────────────────────┴───────────────────────────────┐
│               FastAPI 后端 (Port 8000)                │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │ API: /chat (SSE)  /upload (CSV)  /export (DOCX)│ │
│  └────────────────────┬────────────────────────────┘ │
│                       │                               │
│  ┌────────────────────▼────────────────────────────┐ │
│  │          DataAgentGraph (主编排器)               │ │
│  │  Config(Pydantic) + Propagator + Reflector      │ │
│  │  + TokenTracker + ConditionalLogic              │ │
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
│  │   + Cache(LRU+File) + Core(Config/RateLimit)    │ │
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
├── agent/                      # 7 个 Agent（按角色分目录）
│   ├── __init__.py             # _EXPORTS 懒加载
│   ├── analysts/               # SQL Agent, Chart Agent（工具调用型）
│   ├── debaters/               # Optimistic, Pessimistic（辩论型）
│   ├── managers/               # Planner, Validator（决策/裁判型）
│   ├── synthesis/              # Report Agent（合成型）
│   └── utils/state.py          # AgentState (TypedDict)
├── graph/                      # LangGraph 编排
│   ├── orchestrator.py         # DataAgentGraph 主编排器
│   ├── graph_setup.py          # GraphSetup 图构建
│   ├── conditional_logic.py    # 条件路由（4 个路由器）
│   └── propagation.py          # 初始状态 + 进度标签
├── dataflows/                  # 数据层
│   ├── sqlite_store.py         # SQLite 管理（仅 SELECT）
│   └── demo_data.py            # 演示数据（500+300+200行）
├── memory/                     # 上下文记忆
│   ├── embeddings.py           # 多 Provider Embedding 降级
│   ├── memory_store.py         # ChromaDB 向量存储
│   └── reflector.py            # 分析反思器
├── tools/                      # Agent 工具（@tool 装饰器）
├── cache/adaptive.py           # 三层自适应缓存
├── models/schemas.py           # Pydantic 数据模型
├── core/                       # 配置 + 错误处理 + 限流
├── api/                        # chat(SSE) + upload(CSV) + export(DOCX)
└── utils/                      # 日志 + 降级 + 截断 + 导出
```

## 双 LLM 策略

| 类型 | 温度 | Token | 使用者 | 原因 |
|------|:--:|:--:|------|------|
| quick_think | 0.1 | 4096 | SQL/Chart/Report/Optimistic/Pessimistic | 工具调用需精确 |
| deep_think | 0.3 | 8192 | Planner/Validator | 规划裁判需全面 |

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
| 速率限制 | 滑动窗口，默认 30次/分钟 |
| 异常捕获 | ErrorHandlerMiddleware，按类型返回标准化错误 |
| 死循环防护 | SQL重试≤2, 辩论轮次≤max×2, 驳回修订≤2, 递归≤50 |
