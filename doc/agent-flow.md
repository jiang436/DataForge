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
     ╚══════════════════════════════╝
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
     └──────────────────────────────┘
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

## 上下文记忆

```
分析开始
  ├─ get_historical_context(query) → ChromaDB 检索相似历史
  ├─ 7 Agent 执行
  └─ Validator 通过 → Reflector 提取经验 → 存入 ChromaDB

Embedding 降级:
  阿里云 DashScope → OpenAI API → 本地模型 → 哈希回退
```

## 防护机制

| 机制 | 上限 | 触发行为 |
|------|:--:|------|
| SQL 重试 | 2 | 强制进入下一阶段 |
| SQL 工具调用 | 3 | 死循环防护 |
| 辩论发言 | max×2 | 强制 Validator |
| Validator 驳回 | 2 | 强制 END |
| LangGraph 递归 | 50 | 框架内置保护 |
| 速率限制 | 30/min | 429 Too Many Requests |
