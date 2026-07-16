"""
Agent 评估框架

提供:
  - 多维度 Agent 输出质量评分
  - 批量评估用例运行
  - Markdown 评估报告生成

用法:
    from backend.eval import evaluate_overall

    state = orchestrator.propagate(...)
    report = evaluate_overall(state)
    print(f"总分: {report['overall_score']:.2f}")
"""

from backend.eval.metrics import (
    AgentEvaluation,
    evaluate_chart_agent,
    evaluate_debate_quality,
    evaluate_overall,
    evaluate_report_agent,
    evaluate_sql_agent,
)
from backend.eval.runner import (
    evaluate_single_case,
    format_report_markdown,
    load_eval_cases,
    run_evaluation,
)

__all__ = [
    "AgentEvaluation",
    "evaluate_sql_agent",
    "evaluate_chart_agent",
    "evaluate_report_agent",
    "evaluate_debate_quality",
    "evaluate_overall",
    "evaluate_single_case",
    "run_evaluation",
    "format_report_markdown",
    "load_eval_cases",
]
