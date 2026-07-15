# 面试问答准备

> 理解每个决策的 **Why**，而不是背答案。

---

## 架构设计

### Q1: 为什么用 LangGraph 而不是普通 LangChain Chain？

LangChain 的 Chain 是线性的。我的需求有：
- SQL 执行失败 → 分析错误 → 自动重试（循环）
- 查询结果为空 → 跳过图表（条件跳过）
- 辩论阶段交替发言（循环 + 轮次控制）
- Validator 驳回 → 回到 Report Agent 修正（条件回退）

这些都需要 **有状态的图编排**，LangGraph 的 `StateGraph` + `add_conditional_edges` 正好解决。

### Q2: 为什么 7 个 Agent？太多了吧？

**关注点分离**。每个 Agent 的 System Prompt 只聚焦一个任务：
- Planner 不需要会写 SQL
- SQL Agent 不需要会画图
- Validator 不需要参与辩论

如果一个 Agent 做所有事，prompt 会非常长（2000+ token），准确率反而下降。7 个各司其职，每个 prompt 控制在 200 字以内。

而且 7 个分了三组，面试时一讲就清楚：
- **执行组**（4个）：Planner → SQL → Chart → Report
- **辩论组**（3个）：Optimistic ↔ Pessimistic + DebateScorer
- **裁判组**（1个）：Validator

### Q3: 辩论机制真的有用吗？单个 Agent 出报告不行？

单个 LLM 分析数据容易产生确认偏误（confirmation bias）——看到增长就过于乐观，看到下滑就过于悲观。

正反方对抗性讨论能：
1. **暴露数据矛盾点**："你说增长 23%，但产品 C 8 月下滑 15% 你怎么解释？"
2. **提供多视角**：乐观方看到机会，谨慎方指出风险
3. **类似 peer review**：学术界的同行评审机制

面试时可以直接展示辩论内容给面试官看，对比单 Agent 报告的片面性。

### Q4: 为什么用双 LLM（quick_think / deep_think）？

不同角色对 LLM 的要求不同：

| | quick_think | deep_think |
|---|---|---|
| 温度 | 0.1 | 0.3 |
| Token | 4096 | 8192 |
| 用于 | SQL/Chart/Report/Debate/Scorer | Planner/Validator |
| 原因 | 工具调用必须精确 | 需要全面推理 |

如果全用高温度，SQL Agent 可能生成语法错误。如果全用低温度，Planner 的步骤拆解会太死板。

---

## 技术细节

### Q5: Tool Calling 怎么实现的？

```python
# 1. 定义工具
@tool
def execute_sql(sql: str) -> str: ...

# 2. Agent 绑定工具
chain = prompt | llm.bind_tools([execute_sql])

# 3. LLM 自主判断
#    → 需要查数据? response.tool_calls = [{"name": "execute_sql", ...}]
#    → 不需要? response.content = "分析完成"

# 4. LangGraph ToolNode 自动执行
workflow.add_node("tools_sql", ToolNode([execute_sql]))
# 检测到 tool_calls → 执行函数 → 结果返回 Agent
```

条件路由中检查 `hasattr(message, "tool_calls")` 决定去执行工具还是继续下一步。

### Q6: SQL 写错了怎么处理？

SQL Agent 的条件路由 `route_sql_agent` 检查 state 中的 `sql_error` 字段：

1. execute_sql 执行失败 → 返回 `"ERROR: no such column: xxx"`
2. SQL Agent 检测到 ERROR → 把报错信息作为上下文喂给 LLM
3. LLM 分析错误："列名拼错了"、"忘了加引号" → 生成修正后的 SQL
4. 条件路由判断 `sql_retry_count < 2` → 允许重试
5. 超过 2 次 → 放弃重试，进入下一阶段

### Q7: Validator 怎么判断报告可用？

Validator 做四项检查（有明确权重）：

| 检查项 | 权重 | 具体内容 |
|--------|:--:|------|
| 数据一致性 | 40% | 报告中的数字能否在 SQL 结果中找到？增长率计算正确？ |
| 逻辑一致性 | 30% | 图表趋势和结论是否一致？因果关系推断合理？ |
| 辩论纳入度 | 20% | 正反双方合理观点是否被纳入？ |
| 完整性 | 10% | 是否回答了用户问题？关键指标是否覆盖？ |

Prompt 中给出明确的检查清单和 JSON 输出格式，确保 Validator 输出结构化结果。

### Q8: 为什么用 SSE 而不是 WebSocket？

分析过程是单向的——后端推送进度给前端，用户不需要频繁发消息。

| | SSE | WebSocket |
|---|-----|----------|
| 协议 | HTTP | WS Upgrade |
| 方向 | 单向（服务端→客户端） | 双向 |
| 重连 | 浏览器原生支持 | 需手动实现 |
| Nginx | 禁用缓冲即可 | 需特殊配置 |
| 复杂度 | 低 | 中 |

这里单向推送足够，SSE 更轻量。

### Q9: Agent 之间怎么传递数据？

LangGraph 的 StateGraph 维护统一 TypedDict 状态。每个 Agent 节点读/写同一份 state：

```
Planner 写入 state["plan"]
  → SQL Agent 读取 plan，写入 sql_result
    → Chart Agent 读取 sql_result，写入 chart_json
      → Report Agent 读取 sql_result + chart_json → 写入 draft_report
        → Optimistic/Pessimistic 读取 draft_report
          → DebateScorer 评分后写入 debate_scores
            → Validator 验证后写入 validation_result
              → Eval Runner 评估后写入 eval_results
```

不需要手动传递，LangGraph 的 reducer 自动合并。

### Q10: 上下文记忆怎么工作？

1. **存储**：每次分析完成后，Reflector 提取关键发现和经验教训 → 存入 ChromaDB 向量库
2. **检索**：新分析开始时，用当前问题做语义检索 → 找到最相似的 3 条历史经验
3. **应用**：历史经验注入 Planner 的 prompt，帮助制定更精准的分析计划

Embedding 使用阿里云 DashScope `text-embedding-v3`（1024维），中文语义最优。如果不可用，自动降级到 OpenAI 兼容 API → 本地模型 → 哈希回退。

### Q11: API Key 鉴权怎么做的？

FastAPI 中间件 + 常量时间比较：

1. 白名单路径（/api/health, /docs, /openapi.json）跳过
2. 未配置 API Key → 自动跳过（开发模式）
3. 从 `X-API-Key` Header 或 `?api_key=` Query 参数获取
4. 使用 `hmac.compare_digest()` 常量时间比较，防时序攻击

---

## 项目亮点

### Q12: 这个项目最值得讲的技术点是什么？

按优先级：
1. **LangGraph 条件路由 + 辩论循环 + Validator 驳回修正** — 有状态的 Agent 编排
2. **ReAct 推理循环** — Agent 自主 think→act→observe 多轮迭代
3. **辩论评分体系** — 正反方三维量化评分（论据/数据/反驳），展示 Multi-Agent 附加值
4. **质量评估框架** — 多维度自动评分，成本和质量可视化
5. **ChromaDB 上下文记忆 + 反思学习** — 系统越用越准
6. **多 Provider Embedding 降级** — 阿里云→API→本地→哈希，永不崩溃
7. **自适应缓存三层回退** — 内存 LRU → 文件 → 数据源
8. **Token 用量追踪 + 节点性能统计** — 成本和性能可视化
9. **SQL 安全限制 + 死循环防护** — 生产级防护
10. **Prompt 模板体系** — 9 个独立 Markdown 文件，易于迭代和 A/B 测试

### Q13: 有什么可以改进的？

1. ~~**流式 Token 输出**~~：✅ 已实现。ReAct Agent 内部使用 `llm.stream()`，支持 Token 级逐字推送
2. ~~**Human-in-the-loop**~~：✅ 已实现。Validator JSON 解析失败时设为 `needs_review`，前端可展示人工审核界面
3. ~~**辩论评分**~~：✅ 已实现。DebateScorer 三维独立打分，前端可视化对比
4. ~~**质量评估框架**~~：✅ 已实现。多维指标自动评分，综合分数推送到前端
5. **多数据源**：支持 MySQL/PostgreSQL 直连
6. **并行 Agent**：多个独立分析任务并行执行
7. **Prompt 版本管理**：A/B 测试不同 prompt 效果（已有模板文件基础，便于实现）

---

## v2.0 新增问答

### Q14: 你的 Agent 和普通的 LLM Chain 有什么区别？

v1.0 确实是单次 prompt → LLM → 工具调用 → 返回。但 v2.0 中每个 Agent 内部有真正的 **ReAct 循环**：

1. **Think**: Agent 分析当前状态，判断下一步需要什么
2. **Act**: 调用工具获取信息（SQL Agent 有 3 个工具可选：`get_table_info`、`execute_sql`、`validate_sql`）
3. **Observe**: 阅读工具返回的结果，更新理解
4. **Repeat or Finish**: 需要更多信息就继续，否则输出最终结果

与普通 Chain 的关键差异：
- Chain 是单次固定的，ReAct Agent 是**自适应的多轮推理**
- Agent **自己决定**调用哪些工具、调用几次
- 工具执行结果**实时反馈**给 Agent，影响后续推理

### Q15: 怎么衡量 Agent 的输出质量？

我实现了一个多维度的**评估框架**（`backend/eval/`），每个 Agent 都有量化指标：

| Agent | 评估指标 |
|-------|---------|
| SQL Agent | SQL 语法正确性(30%) + 结果非空(30%) + 错误恢复(20%) + ReAct 效率(20%) |
| Chart Agent | 图表生成率(50%) + 数据适配性(30%) + 迭代效率(20%) |
| Report Agent | 字数(25%) + 无幻觉(35%) + 结构完整性(25%) + 数据引用(15%) |
| 辩论 | 双方参与(30%) + 反驳质量(30%) + 数据支撑(25%) + 评分可用(15%) |

每次分析完成后自动运行评估，综合分数存入 state，可通过 SSE 推送到前端。

### Q16: 辩论怎么评分？怎么知道辩论有用？

我实现了 `DebateScorer`（`backend/agent/debaters/scorer.py`），让 LLM 从三个维度对正反方独立打分：

- **论据质量（40分）**: 逻辑是否严密、是否有因果推断
- **数据支撑（40分）**: 引用的数据是否与 SQL 结果一致、解读是否合理
- **反驳力度（20分）**: 是否有效回应对手核心论点

辩论评分展示了 Multi-Agent 协作的附加价值——如果双方分数都很低，说明数据本身不够支撑分析；如果正反方分数悬殊，说明一个视角明显更可靠。

### Q17: 你的 ReAct 循环怎么防止无限循环？

三重防护：
1. **max_iterations=5**: 硬性上限，超过直接停止
2. **stream_callback 异常保护**: 流式回调失败不影响主逻辑
3. **工具调用异常降级**: 工具执行失败时返回错误信息给 Agent，Agent 可以基于错误调整策略，而非死循环重试

### Q18: 为什么用 contextvars 传递流式回调而不是改函数签名？

contextvars 是 Python 3.7+ 的标准库，专为异步上下文设计。不改函数签名的原因：

1. Agent 工厂函数 → LangGraph 节点 → ReAct 循环的调用链很深，每个函数都加参数会污染接口
2. contextvars 天然支持 per-request 隔离（每个 SSE 连接有独立上下文）
3. FastAPI 的 `contextvars.copy_context()` 确保线程安全

面试话术: "这跟 Flask 的 request context、Django 的 thread local 模式一样——Python 生态中这是成熟的模式。"

### Q19: CI/CD 怎么配置的？

GitHub Actions 自动化流水线（[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)）：

**Backend Job** (矩阵测试 Python 3.10/3.11/3.12):
1. `ruff check` — 代码检查
2. `ruff format --check` — 格式检查
3. `pytest tests/ -v` — 运行 232 个后端测试

**Frontend Job**:
1. `npm ci` — 依赖安装
2. `vue-tsc --noEmit` — TypeScript 类型检查
3. `vitest run` — 运行 17 个前端测试
4. `npm run build` — 生产构建

触发条件：push/PR 到 main 分支。

### Q20: 前端 Design Tokens 是什么？为什么不用 Tailwind？

设计决策——我选择原生 CSS 自定义属性（`tokens.css`）而不是 Tailwind：

1. **面试展示力**: 定义完整的 Design Token 体系（颜色/圆角/阴影/动效/字体/间距），体现对视觉一致性的理解
2. **零运行时**: CSS 变量原生，无 JS 开销
3. **主题切换基础**: 变量体系天然支持未来的明暗主题切换
4. **团队协作**: Token 命名即设计语言，设计师可以直接理解

Token 体系覆盖：
- Canvas（背景/表面/边框色）
- Ink（文字色四级层次）
- Accent（Emerald 强调色）
- 语义色（琥珀/红/蓝/紫 + 对应背景/边框）
- Sidebar 专属暗色变量
- 形状系统（sm/md/lg/xl 四级圆角）
- 阴影系统（card/elevated/none）
- 动效（缓动函数 + 时长）
- 字体栈（系统字体优先，零外部加载）

### Q21: 测试是怎么分层的？

总分 **249 个测试**（232 后端 + 17 前端），按测试金字塔分层：

| 层级 | 测试文件 | 数量 | 特点 |
|------|---------|:--:|------|
| 单元 | test_sqlite_store, test_tools, test_token_tracker, test_propagation, chat.test.ts | ~50 | 纯逻辑，无外部依赖 |
| 集成 | test_agents, test_agent_prompts, test_agent_reasoning, test_react_agent, test_conditional_logic | ~80 | 依赖 FakeLLM |
| 组件 | test_orchestrator, test_eval, test_integration | ~60 | 依赖 FakeLLM + 内存数据库 |
| 端到端 | test_dataflows, test_integration_real_tools, test_e2e, test_performance | ~60 | 真实工具 + 真实数据流 |

`FakeLLM`（`tests/mock_llm.py`）是测试基石——模拟 LLM 响应，支持：
- 按预设顺序返回文本/工具调用
- 流式和非流式两种模式
- 完整的 call_history 记录用于断言

---

## 对比参考

这个项目的架构参考了 [TradingAgents-CN](https://github.com/TauricResearch/TradingAgents)（一个学术论文的 Multi-Agent 股票分析系统），保留了其核心模式：

| 模式 | 说明 |
|------|------|
| StateGraph + 条件路由 | LangGraph 有状态图编排 |
| Agent 工厂模式 | `create_xxx(llm) → 闭包` |
| ToolNode 分组 | 每个 Agent 配专用 ToolNode |
| 辩论循环 | Bull/Bear 模式迁移到 Optimistic/Pessimistic |
| 裁判机制 | Research Manager → Validator |
| LLM 工厂 | 多 Provider 一键切换 |
| ChromaDB 记忆 | FinancialSituationMemory → AnalysisMemory |

但做了大幅简化：11 Agent → 7 Agent，MongoDB+Redis → SQLite+文件，Streamlit → Vue 3，A股金融 → 通用数据分析。新增：辩论评分、质量评估框架、Prompt 模板体系、Design Tokens、CI/CD。
