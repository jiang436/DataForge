# Agent 执行流程详解

## 完整流程

```
用户: "分析Q3各产品线增长趋势，Top5作图"
                    │
     ┌──────────────▼──────────────┐
     │      ① Planner              │  deep_think_llm (T=0.3)
     │  输出: [{step:1, task:"汇总月度销售", type:"sql"}, ...]
     └──────────────┬──────────────┘
                    │
     ┌──────────────▼──────────────┐
     │      ② SQL Agent            │  quick_think_llm + bind_tools
     │  SELECT product, strftime(   │
     │  '%Y-%m',date) as month,     │
     │  SUM(amount) FROM sales      │
     │  GROUP BY ... → 36行         │
     │         │                    │
     │    ┌────▼────┐               │
     │    │tools_sql│ ← ToolNode    │
     │    └────┬────┘               │
     │         │ 返回36行           │
     │    ┌────▼────┐               │
     │    │SQL Agent│ 出错? → 重试   │
     │    └────┬────┘               │
     └─────────┼────────────────────┘
               │
     ┌─────────▼────────────────────┐
     │    Msg Clear SQL             │  清理消息，防 token 膨胀
     └─────────┬────────────────────┘
               │
     ┌─────────▼────────────────────┐
     │      ③ Chart Agent           │  quick_think_llm + bind_tools
     │  generate_chart(type="line", │
     │  title="产品线Q3趋势",        │
     │  x="month", y="total",       │
     │  group="product")            │
     │    → Plotly JSON             │
     └─────────┬────────────────────┘
               │
     ┌─────────▼────────────────────┐
     │    Msg Clear Chart           │
     └─────────┬────────────────────┘
               │
     ┌─────────▼────────────────────┐
     │      ④ Report Agent          │
     │  ## 数据概览                  │
     │  Q3总销售额580万，环比+23%     │
     │  ## 产品表现                  │
     │  产品A领跑(+35%), C下滑(-8%)  │
     └─────────┬────────────────────┘
               │
     ╔═════════▼════════════════════╗
     ║      🔥 辩论阶段 (2轮)        ║
     ║                              ║
     ║  Optimistic: "Q3增长23%大好！ ║
     ║   产品A应加大投入" → count=1  ║
     ║           ↓                  ║
     ║  Pessimistic: "但C下滑15%，   ║
     ║   增速放缓需警惕" → count=2   ║
     ║           ↓                  ║
     ║  Optimistic: "下滑是季节性"   ║
     ║   → count=3                  ║
     ║           ↓                  ║
     ║  Pessimistic: "幅度比去年大"  ║
     ║   → count=4                  ║
     ║                              ║
     ║  count(4) >= max(4) → 结束   ║
     ╚══════════┬═══════════════════╝
                │
     ┌──────────▼──────────────────┐
     │    🏆 DebateScorer 评分      │  quick_think_llm
     │  正方: 论据38/数据35/反驳15  │
     │  反方: 论据32/数据38/反驳18  │
     │  胜方: 正方 (总体88 vs 88平) │
     └──────────┬──────────────────┘
                │
     ┌─────────▼────────────────────┐
     │      ⑦ Validator             │  deep_think_llm
     │  三方一致性检查:               │
     │  ① SQL结果 ↔ 报告数字         │
     │  ② 图表趋势 ↔ 结论            │
     │  ③ 双方观点是否纳入           │
     │                              │
     │  approved → END ✅            │
     │  rejected → Report修正(≤2次)  │
     └──────────┬──────────────────┘
                │
     ┌──────────▼──────────────────┐
     │    📊 质量评估 (Eval)         │  事后自动评分
     │  SQL正确性 + 报告幻觉检测     │
     │  + 图表适配性 + 辩论数据支撑   │
     │  → 综合分数推送到前端          │
     └─────────────────────────────┘
```

## 条件路由

### SQL Agent

```
messages[-1] 有 tool_calls?
  ├─ retry>=3? → Msg Clear SQL (死循环防护)
  └─ 否则 → tools_sql

sql_error 存在 && retry<2?
  └─ → SQL Agent (重试)

默认 → Msg Clear SQL
```

### 辩论

```
debate_state.round_count >= max × 2?
  └─ → DebateScorer (辩论评分)

debate_state.round_count >= max × 2 + 1?
  └─ → Validator

latest_speaker == "optimistic"?
  └─ → Pessimistic : Optimistic
```

### Validator

```
approved? → END
revision >= 2? → END (上限)
否则 → Report Agent
```

## ReAct 推理循环

每个 Agent 内部执行 ReAct (Reasoning + Acting) 循环：

```
┌─→ Think ─→ Act ─→ Observe ─┐
│                             │
└───────── 重复 ≤5次 ─────────┘
                    │
                    ▼
              最终输出
```

| 步骤 | 说明 |
|------|------|
| Think | Agent 分析当前状态和上下文，判断需要什么信息 |
| Act | 调用工具（如 `get_table_info`、`execute_sql`、`validate_sql`） |
| Observe | 阅读工具返回结果，更新理解，决定是否继续 |
| Repeat | 需要更多信息？继续循环。完成？输出最终结果。 |

与普通 Chain 的差异：
- Chain 是单次固定的，ReAct Agent 是**自适应的多轮推理**
- Agent **自己决定**调用哪些工具、调用几次
- 工具执行结果**实时反馈**给 Agent，影响后续推理

## 辩论评分机制

`DebateScorer` 在辩论结束后独立调用 LLM 评分：

| 维度 | 满分 | 评估要点 |
|------|:--:|------|
| 论据质量 | 40 | 逻辑是否严密、因果关系推断是否合理 |
| 数据支撑 | 40 | 引用的数据是否与 SQL 结果一致、解读是否合理 |
| 反驳力度 | 20 | 是否有效回应对手核心论点、是否揭露对方数据盲区 |

评分输出为 JSON，包含双方分项得分、总分和胜方判定。结果通过 SSE 推送到前端展示。

## 质量评估框架

`backend/eval/` 在分析完成后自动评估各 Agent 输出质量：

| Agent | 评估维度 | 权重分配 |
|-------|---------|---------|
| SQL Agent | 语法正确 / 结果非空 / 错误恢复 / ReAct效率 | 30/30/20/20 |
| Chart Agent | 图表生成率 / 数据适配性 / 迭代效率 | 50/30/20 |
| Report Agent | 字数 / 无幻觉 / 结构完整性 / 数据引用 | 25/35/25/15 |
| 辩论质量 | 双方参与 / 反驳质量 / 数据支撑 / 评分可用 | 30/30/25/15 |

综合分数 = 各 Agent 加权平均，结果通过 SSE 推送到前端。

## 上下文记忆

```
分析开始
  ├─ get_historical_context(query) → ChromaDB 检索相似历史
  ├─ 7 Agent 执行
  ├─ 辩论评分 (DebateScorer)
  ├─ Validator 通过 → Reflector 提取经验 → 存入 ChromaDB
  └─ 质量评估 (Eval)

Embedding 降级:
  阿里云 DashScope → OpenAI API → 本地模型 → 哈希回退
```

## 防护机制

| 机制 | 上限 | 触发行为 |
|------|:--:|------|
| SQL 重试 | 2 | 强制进入下一阶段 |
| SQL 工具调用 | 3 | 死循环防护 |
| ReAct 迭代 | 5 | Agent 内部循环上限 |
| 辩论发言 | max×2 | 强制 Validator |
| Validator 驳回 | 2 | 强制 END |
| LangGraph 递归 | 50 | 框架内置保护 |
| 速率限制 | 30/min | 429 Too Many Requests |
