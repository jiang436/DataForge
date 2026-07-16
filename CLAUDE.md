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
| 测试 | Pytest (324 tests), Vitest (17 tests) |
| 包管理 | UV (uv sync / uv pip install) |

## 常用命令

```bash
# 启动后端 (port 4433)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 4433 --reload

# 启动前端 (port 5173, 自动 proxy → 4433)
cd frontend && npm run dev

# 运行全部测试 (320 passed, 4 old-failures, 2 skipped)
python -m pytest tests/ -v

# 运行前端测试
cd frontend && npx vitest run

# 代码检查
python -m ruff check backend/ tests/
python -m ruff format backend/ tests/

# 生成架构流程图 (Mermaid → PNG)
python scripts/gen_diagrams.py

# 真实 API 性能基准测试
python scripts/real_benchmark.py
```

## 项目结构

```
backend/          # Python 后端 (~66 files)
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
    components/AgentDashboard.vue   # [新] Agent 实时状态面板
    components/ReportPanel.vue      # [新] 报告展示面板
    stores/chat.ts           # Pinia 状态管理
    composables/useSSE.ts    # SSE 流式封装
    styles/tokens.css        # Design Tokens v2
    __tests__/chat.test.ts   # 前端测试 (17)

tests/            # 后端测试 (324 用例, 20 文件)
  mock_llm.py              # FakeLLM — 模拟 LLM (测试基石)
  test_hallucination.py    # [新] Agent 幻觉检测 (18)
  test_llm_robustness.py   # [新] LLM 输出格式容错 (25)
  test_sql_security.py     # [新] SQL 注入防护 (24)
  test_debate_quality.py   # [新] 辩论质量回归 (13)
  test_multi_turn.py       # [新] 多轮对话上下文 (12)

scripts/          # 辅助脚本
  gen_diagrams.py          # Mermaid 流程图 → PNG
  real_benchmark.py        # DeepSeek API 性能基准测试
```

## 7 个 Agent 执行流程

```
Planner → SQL Agent ⇄ tools_sql → Chart Agent ⇄ tools_chart
→ Report Agent → Optimistic ↔ Pessimistic (辩论)
→ DebateScorer (评分) → Validator → END / 驳回修正 (≤3次)
→ Eval (质量评估)
```

## LLM 配置

- Provider: 由 `.env` 中的 `LLM_PROVIDER` 控制
- 双 LLM 策略: quick_think (T=0.1, 4096 token) / deep_think (T=0.3, 8192 token)
- API Key 鉴权: 中间件 + `hmac.compare_digest()`，开发模式自动跳过
- TokenTracker: 已实现（线程安全），尚未接入 LLM 回调链

## Validator v3.2 变更

- 新增 `approved_with_suggestions` 状态：通过但附优化建议，不触发修订循环
- 最大修订次数 2 → 3
- Prompt 软化：±2% 数值差异、图表标注问题、措辞可优化视为通过
- 只拒绝对用户决策有实质影响的重大错误

## 关键设计决策

- **为什么不直接用 Chain**: 需要条件路由 (SQL失败重试/跳过图表/辩论轮次/Validator驳回)
- **为什么 7 个 Agent**: 关注点分离，每个 prompt 聚焦单一任务
- **为什么 SSE 而非 WebSocket**: 单向推送足够，更轻量
- **为什么 SQLite**: 零配置，面试现场一键启动
- **为什么 ChromaDB**: 本地持久化，Python 内嵌，零运维

## README 流程图规范

- 架构图直接使用 **Mermaid 代码块**（GitHub 原生渲染 + 交互缩放/拖拽/全屏）
- 不要导出 PNG — 静态图无交互面板
- 方向优先 `flowchart LR`（横向利用页面宽度），避免 `TD`（竖向又窄又小）
- 条件路由用 `flowchart` + `subgraph` 分组，不用 `stateDiagram-v2`（嵌套状态难懂）
- 界面截图用 PNG (`docs/images/`)，架构图用 Mermaid，泾渭分明
- 详细规范见 `.claude/skills/project-readme-authoring.md`
