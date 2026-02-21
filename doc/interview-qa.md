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
- **辩论组**（2个）：Optimistic ↔ Pessimistic
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
| 用于 | SQL/Chart/Report/Debate | Planner/Validator |
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
          → Validator 写入 validation_result
```

不需要手动传递，LangGraph 的 reducer 自动合并。

### Q10: 上下文记忆怎么工作？

1. **存储**：每次分析完成后，Reflector 提取关键发现和经验教训 → 存入 ChromaDB 向量库
2. **检索**：新分析开始时，用当前问题做语义检索 → 找到最相似的 3 条历史经验
3. **应用**：历史经验注入 Planner 的 prompt，帮助制定更精准的分析计划

Embedding 使用阿里云 DashScope `text-embedding-v3`（1024维），中文语义最优。如果不可用，自动降级到 OpenAI 兼容 API → 本地模型 → 哈希回退。

---

## 项目亮点

### Q11: 这个项目最值得讲的技术点是什么？

按优先级：
1. **LangGraph 条件路由 + 辩论循环 + Validator 驳回修正** — 有状态的 Agent 编排
2. **ChromaDB 上下文记忆 + 反思学习** — 系统越用越准
3. **多 Provider Embedding 降级** — 阿里云→API→本地→哈希，永不崩溃
4. **自适应缓存三层回退** — 内存 LRU → 文件 → 数据源
5. **Token 用量追踪 + 节点性能统计** — 成本和性能可视化
6. **SQL 安全限制 + 死循环防护** — 生产级防护

### Q12: 有什么可以改进的？

1. **流式 Token 输出**：目前是节点级推送，可做到 Token 级逐字推送
2. **Human-in-the-loop**：Validator 驳回时加入人工确认节点
3. **多数据源**：支持 MySQL/PostgreSQL 直连
4. **并行 Agent**：多个独立分析任务并行执行
5. **Prompt 版本管理**：A/B 测试不同 prompt 效果

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

但做了大幅简化：11 Agent → 7 Agent，MongoDB+Redis → SQLite+文件，Streamlit → Vue 3，A股金融 → 通用数据分析。
