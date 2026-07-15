# CLAUDE.md — DataForge AI 项目说明

## 项目概述

DataForge AI 是一个 **Multi-Agent 数据分析系统**，7 个 AI Agent 通过 ReAct 循环 + LangGraph 编排协作，将 CSV 数据自动转化为带图表的分析报告。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+, FastAPI, Uvicorn, LangGraph, LangChain |
| 前端 | Vue 3, Vite, Pinia, TypeScript, Element Plus, Plotly.js |
| 数据 | SQLite (内置), ChromaDB (向量记忆) |
| LLM | DeepSeek (默认), 支持 OpenAI/Qwen/GLM/SiliconFlow |
| 测试 | Pytest (232 tests), Vitest (17 tests) |

## 常用命令

```bash
# 启动后端 (port 4433)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 4433 --reload

# 启动前端 (port 5173, 自动 proxy → 4433)
cd frontend && npm run dev

# 运行全部测试
python -m pytest tests/ -v

# 运行前端测试
cd frontend && npx vitest run

# 代码检查
python -m ruff check backend/ tests/
python -m ruff format backend/ tests/
```

## 项目结构

```
backend/          # Python 后端 (~60 files)
  main.py         # FastAPI 入口, lifespan
  agent/          # 7 个 Agent (analysts/debaters/managers/synthesis)
  graph/          # LangGraph 编排层 (orchestrator/graph_setup/conditional_logic)
  api/            # chat(SSE), upload(CSV), export(DOCX)
  prompts/        # 9 个 Agent Prompt 模板 (Markdown)
  eval/           # 质量评估框架 (metrics + runner)
  core/           # 配置, 鉴权, 错误处理, 限流
  dataflows/      # SQLite CRUD + 安全限制
  memory/         # ChromaDB 向量记忆 + Embedding 降级
  tools/          # Agent 工具 (execute_sql, generate_chart)
  llm_clients/    # LLM 工厂 + Provider 配置
  cache/          # 三层自适应缓存
  utils/          # 日志, JSON解析, 文本截断, 报告导出

frontend/         # Vue 3 前端
  src/
    App.vue       # 主布局 (暗色侧边栏 + 对话区)
    views/AnalysisView.vue  # 对话视图
    components/DataUploader.vue, ChartCard.vue
    stores/chat.ts           # Pinia 状态管理
    composables/useSSE.ts    # SSE 流式封装
    styles/tokens.css        # Design Tokens
    __tests__/chat.test.ts   # 前端测试 (17)

tests/            # 后端测试 (232)
  mock_llm.py     # FakeLLM — 模拟 LLM (测试基石)
```

## 7 个 Agent 执行流程

```
Planner → SQL Agent ⇄ tools_sql → Chart Agent ⇄ tools_chart
→ Report Agent → Optimistic ↔ Pessimistic (辩论)
→ DebateScorer (评分) → Validator → END / 驳回修正
→ Eval (质量评估)
```

## LLM 配置

- Provider: 由 `.env` 中的 `LLM_PROVIDER` 控制
- 双 LLM 策略: quick_think (T=0.1, 4096 token) / deep_think (T=0.3, 8192 token)
- API Key 鉴权: 中间件 + `hmac.compare_digest()`，开发模式自动跳过

## 关键设计决策

- **为什么不直接用 Chain**: 需要条件路由 (SQL失败重试/跳过图表/辩论轮次/Validator驳回)
- **为什么 7 个 Agent**: 关注点分离，每个 prompt 聚焦单一任务
- **为什么 SSE 而非 WebSocket**: 单向推送足够，更轻量
- **为什么 SQLite**: 零配置，面试现场一键启动
- **为什么 ChromaDB**: 本地持久化，Python 内嵌，零运维
