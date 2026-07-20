"""
Agent 评估指标 — 衡量每个 Agent 的输出质量

包括 SQL 准确率、报告幻觉检测、辩论数据支撑度等。
"""

from dataclasses import dataclass, field


@dataclass
class AgentEvaluation:
    """单个 Agent 的评估结果"""
    agent_name: str
    score: float  # 0.0 - 1.0
    metrics: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: str = ""


def evaluate_sql_agent(state: dict) -> AgentEvaluation:
    """
    评估 SQL Agent 的输出质量。

    指标:
      - sql_syntax_valid: SQL 是否执行成功（权重 30%）
      - result_non_empty: 是否返回了有意义的数据（权重 30%）
      - error_recovery: 是否从错误中恢复（权重 20%）
      - iterations_efficiency: ReAct 迭代次数是否合理（权重 20%）
    """
    metrics = {}
    warnings = []
    errors = []

    sql = state.get("sql_query", "")
    result = state.get("sql_result", "")
    error = state.get("sql_error", "")
    iterations = state.get("react_iterations", 1)

    # SQL 语法正确性
    metrics["sql_syntax_valid"] = 1.0 if not error else 0.0
    # 结果非空
    has_data = result and "(查询成功，但无返回数据)" not in result and len(result) > 20
    metrics["result_non_empty"] = 1.0 if has_data else 0.3
    # 错误恢复
    metrics["error_recovery"] = 1.0 if not error else (0.5 if iterations > 1 else 0.0)
    # ReAct 效率（超过3轮扣分）
    metrics["iterations_efficiency"] = 1.0 if iterations <= 3 else max(0.0, 1.0 - (iterations - 3) * 0.2)

    if error:
        warnings.append(f"SQL 执行错误: {error[:150]}")
    if not sql:
        warnings.append("未生成 SQL 查询")

    score = sum(metrics.values()) / max(len(metrics), 1)

    return AgentEvaluation(
        agent_name="SQL Agent",
        score=round(score, 2),
        metrics=metrics,
        errors=errors,
        warnings=warnings,
    )


def evaluate_report_agent(state: dict) -> AgentEvaluation:
    """
    评估 Report Agent 的输出质量。

    指标:
      - min_length: 报告是否足够详细（权重 25%）
      - no_hallucination: 是否使用假设性语言（权重 35%）
      - structure: Markdown 结构完整性（权重 25%）
      - data_references: 是否引用具体数据（权重 15%）
    """
    report = state.get("draft_report", "")
    metrics = {}
    warnings = []

    # 长度
    report_len = len(report)
    metrics["min_length"] = 1.0 if report_len > 300 else (report_len / 300)
    # 无幻觉
    hallucination_words = ["假设", "例如假设", "假设性", "典型数据", "假设有", "假如"]
    hallu_count = sum(1 for w in hallucination_words if w in report.lower())
    metrics["no_hallucination"] = 1.0 if hallu_count == 0 else max(0.0, 1.0 - hallu_count * 0.3)
    # 结构
    structure_score = 0.0
    if "##" in report:
        structure_score += 0.4
    if "|" in report and "-|-" in report.replace(" ", ""):
        structure_score += 0.3
    if "- " in report:
        structure_score += 0.3
    metrics["structure"] = min(1.0, structure_score)
    # 数据引用
    digit_count = sum(1 for c in report[:1000] if c.isdigit())
    metrics["data_references"] = 1.0 if digit_count > 20 else (digit_count / 20)

    if report_len < 100:
        warnings.append(f"报告过短 ({report_len} 字符)")
    if hallu_count > 0:
        warnings.append(f"检测到 {hallu_count} 处疑似幻觉表述")
    if "##" not in report:
        warnings.append("报告缺少 Markdown 标题结构")

    score = sum(metrics.values()) / max(len(metrics), 1)

    return AgentEvaluation(
        agent_name="Report Agent",
        score=round(score, 2),
        metrics=metrics,
        errors=[],
        warnings=warnings,
    )


def evaluate_chart_agent(state: dict) -> AgentEvaluation:
    """
    评估 Chart Agent 的输出质量。

    指标:
      - chart_generated: 是否生成了图表（权重 50%）
      - data_appropriate: 数据是否适合做图（权重 30%）
      - iterations_efficient: 是否高效完成（权重 20%）
    """
    metrics = {}
    warnings = []

    chart = state.get("chart_json")
    sql_result = state.get("sql_result", "")
    iterations = state.get("react_iterations", 1)

    metrics["chart_generated"] = 1.0 if chart else 0.0
    # 数据适配性：有数据但没生成图表 = 扣分
    has_data = sql_result and "(查询成功，但无返回数据)" not in sql_result
    if has_data:
        metrics["data_appropriate"] = 1.0 if chart else 0.5
    else:
        metrics["data_appropriate"] = 1.0  # 无数据不生成图表是正确的
    metrics["iterations_efficient"] = 1.0 if iterations <= 2 else 0.5

    if has_data and not chart:
        warnings.append("有查询数据但未生成图表")
    if chart and not has_data:
        warnings.append("生成了图表但没有查询数据（可能为编造）")

    score = sum(metrics.values()) / max(len(metrics), 1)

    return AgentEvaluation(
        agent_name="Chart Agent",
        score=round(score, 2),
        metrics=metrics,
        errors=[],
        warnings=warnings,
    )


def evaluate_debate_quality(state: dict) -> AgentEvaluation:
    """
    评估辩论质量。

    指标:
      - both_sides_participated: 双方是否都参与了（权重 30%）
      - counter_arguments: 是否有反驳（权重 30%）
      - data_supported: 论据是否有数据支撑（权重 25%）
      - scoring_available: 是否有辩论评分（权重 15%）
    """
    opt_view = state.get("optimistic_view", "")
    pess_view = state.get("pessimistic_view", "")
    debate_scores = state.get("debate_scores")

    metrics = {}
    warnings = []

    metrics["both_sides_participated"] = 1.0 if opt_view and pess_view else 0.0
    metrics["counter_arguments"] = 1.0 if ("反驳" in opt_view or "反驳" in pess_view) else 0.5
    # 数据支撑检测
    data_keywords = ["%", "万", "元", "增长", "下滑", "提升", "下降", "提升", "最高", "最低"]
    opt_data = any(w in opt_view for w in data_keywords)
    pess_data = any(w in pess_view for w in data_keywords)
    metrics["data_supported"] = (opt_data + pess_data) / 2.0
    metrics["scoring_available"] = 1.0 if debate_scores else 0.0

    if not opt_view:
        warnings.append("正方未发言")
    if not pess_view:
        warnings.append("反方未发言")
    if metrics["data_supported"] < 0.5:
        warnings.append("辩论缺乏数据支撑")

    score = sum(metrics.values()) / max(len(metrics), 1)

    return AgentEvaluation(
        agent_name="Debate",
        score=round(score, 2),
        metrics=metrics,
        errors=[],
        warnings=warnings,
    )


def evaluate_overall(state: dict) -> dict:
    """
    综合评估所有 Agent 的输出质量。

    Returns:
        {
            "overall_score": 0.85,
            "evaluations": { "SQL Agent": {...}, "Chart Agent": {...}, ... },
            "warnings": [...],
            "passed": true
        }
    """
    evaluations = {
        "SQL Agent": evaluate_sql_agent(state),
        "Chart Agent": evaluate_chart_agent(state),
        "Report Agent": evaluate_report_agent(state),
        "Debate": evaluate_debate_quality(state),
    }

    scores = [e.score for e in evaluations.values()]
    overall = sum(scores) / max(len(scores), 1)
    all_warnings = []
    for e in evaluations.values():
        all_warnings.extend(e.warnings)

    return {
        "overall_score": round(overall, 2),
        "evaluations": {
            name: {
                "score": e.score,
                "metrics": e.metrics,
                "warnings": e.warnings,
            }
            for name, e in evaluations.items()
        },
        "warnings": all_warnings,
        "passed": overall >= 0.5,
    }
