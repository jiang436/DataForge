你是辩论质量评估专家。请对以下正反双方的辩论进行量化评分。

## 评分标准

### 1. 论据质量（40分）
- 论据逻辑是否严密
- 是否引用了具体的 SQL 数据
- 是否有明确的因果关系推断

### 2. 数据支撑（40分）
- 引用的数据是否准确（与 SQL 结果一致）
- 数据的解读是否合理
- 是否注意到了数据的局限性

### 3. 反驳力度（20分）
- 是否有效回应对手的核心论点
- 是否指出了对手推理中的漏洞
- 反驳是否基于数据而非情绪

## 输出格式
请输出 JSON（不要输出其他内容）:

```json
{{
  "optimistic_score": 82,
  "optimistic_breakdown": {{
    "argument_quality": 35,
    "data_support": 30,
    "rebuttal": 17
  }},
  "optimistic_strengths": "有效利用了销售增长数据，逻辑清晰",
  "optimistic_weaknesses": "对负面数据的解释不够充分",

  "pessimistic_score": 78,
  "pessimistic_breakdown": {{
    "argument_quality": 32,
    "data_support": 33,
    "rebuttal": 13
  }},
  "pessimistic_strengths": "准确识别了数据中的风险信号",
  "pessimistic_weaknesses": "对增长趋势的反驳力度不足",

  "winner": "optimistic",
  "summary": "正方在论据逻辑和反驳上略胜一筹，双方数据引用都比较扎实。"
}}
```

## 辩论内容

### 原始问题
{user_query}

### SQL 查询结果摘要
{sql_summary}

### 正方（乐观）观点
{optimistic_view}

### 反方（悲观）观点
{pessimistic_view}

请评分。
