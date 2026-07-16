"""
评估运行器 — 批量跑测试用例 + 汇总报告

用法:
    python -m backend.eval.runner              # 运行所有评估用例
    python -m backend.eval.runner --verbose    # 详细模式
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("eval")


def load_eval_cases(cases_dir: str | None = None) -> list[dict]:
    """
    加载评估用例

    用例格式 (JSON):
    {
        "id": "case_001",
        "name": "基础查询 - 销量最高品牌",
        "query": "哪个品牌销量最高？",
        "tables": ["电子产品销售数据"],
        "ground_truth": {
            "expected_brand": "戴尔",
            "min_report_length": 200,
            "should_have_chart": true
        },
        "eval_rules": ["brand_correct", "report_has_data", "chart_generated"]
    }
    """
    if cases_dir is None:
        cases_dir = str(Path(__file__).parent.parent.parent / "tests" / "eval_data")

    cases = []
    cases_path = Path(cases_dir)
    if not cases_path.exists():
        logger.warning("评估用例目录不存在: %s", cases_dir)
        return _default_cases()

    for f in sorted(cases_path.glob("*.json")):
        try:
            case = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(case, list):
                cases.extend(case)
            else:
                cases.append(case)
        except Exception as e:
            logger.warning("加载用例失败 %s: %s", f.name, e)

    return cases if cases else _default_cases()


def _default_cases() -> list[dict]:
    """内置默认评估用例"""
    return [
        {
            "id": "builtin_001",
            "name": "报告质量 — 字数检查",
            "query": "电子产品销售表有多少行？",
            "eval_rules": ["min_report_length"],
            "min_report_length": 100,
        },
        {
            "id": "builtin_002",
            "name": "报告质量 — 无幻觉",
            "query": "各品牌平均好评率是多少？",
            "eval_rules": ["no_hallucination"],
        },
        {
            "id": "builtin_003",
            "name": "SQL质量 — 查询成功",
            "query": "按品牌统计销量总和",
            "eval_rules": ["sql_success"],
        },
    ]


def evaluate_single_case(
    state: dict,
    case: dict,
    evaluator: Any = None,
) -> dict:
    """
    对单个用例进行离线评估（不依赖实际 LLM 调用）。

    使用 state 中已收集的 Agent 输出进行评分。
    """
    from backend.eval.metrics import evaluate_overall

    result = evaluate_overall(state)
    rules = case.get("eval_rules", [])

    rule_results = {}
    for rule in rules:
        if rule == "min_report_length":
            min_len = case.get("min_report_length", 200)
            report = state.get("draft_report", "")
            rule_results[rule] = len(report) >= min_len
        elif rule == "no_hallucination":
            report = state.get("draft_report", "")
            hallu = ["假设", "假设性", "典型数据", "假如"]
            rule_results[rule] = not any(w in report.lower() for w in hallu)
        elif rule == "sql_success":
            error = state.get("sql_error", "")
            sql = state.get("sql_query", "")
            rule_results[rule] = not error and bool(sql)
        elif rule == "chart_generated":
            chart = state.get("chart_json")
            rule_results[rule] = chart is not None
        elif rule == "brand_correct":
            report = state.get("draft_report", "")
            expected = case.get("ground_truth", {}).get("expected_brand", "")
            rule_results[rule] = expected.lower() in report.lower() if expected else True
        elif rule == "report_has_data":
            report = state.get("draft_report", "")
            rule_results[rule] = any(c.isdigit() for c in report[:500])
        else:
            rule_results[rule] = None  # 未知规则

    return {
        "case_id": case["id"],
        "case_name": case.get("name", case["id"]),
        "overall_score": result["overall_score"],
        "rule_results": rule_results,
        "agent_evaluations": result["evaluations"],
        "warnings": result["warnings"],
        "passed": result["passed"] and all(
            v for v in rule_results.values() if v is not None
        ),
    }


def run_evaluation(
    states: list[dict],
    cases: list[dict] | None = None,
    verbose: bool = False,
) -> dict:
    """
    批量运行评估

    Args:
        states: 分析完成后的 state 列表
        cases:  对应的评估用例列表（为空则用默认规则）
        verbose: 是否打印详细信息

    Returns:
        汇总评估报告
    """
    if cases is None:
        cases = _default_cases()

    results = []
    for i, state in enumerate(states):
        case = cases[i] if i < len(cases) else _default_cases()[0]
        result = evaluate_single_case(state, case)
        results.append(result)

        if verbose:
            status = "✅" if result["passed"] else "❌"
            print(f"\n{status} [{result['case_id']}] {result['case_name']}")
            print(f"   总分: {result['overall_score']:.2f}")
            for rule, passed in result["rule_results"].items():
                r_status = "✅" if passed else ("❌" if passed is False else "⬜")
                print(f"   {r_status} {rule}")
            if result["warnings"]:
                for w in result["warnings"]:
                    print(f"   ⚠️  {w}")

    passed_count = sum(1 for r in results if r["passed"])
    avg_score = sum(r["overall_score"] for r in results) / max(len(results), 1)

    report = {
        "total_cases": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "average_score": round(avg_score, 2),
        "results": results,
    }

    print(f"\n{'='*50}")
    print(f"评估完成: {passed_count}/{len(results)} 通过, 平均分 {avg_score:.2f}")
    print(f"{'='*50}")

    return report


def format_report_markdown(report: dict) -> str:
    """将评估报告格式化为 Markdown"""
    lines = [
        "# Agent 评估报告",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 总用例数 | {report['total_cases']} |",
        f"| 通过 | {report['passed']} |",
        f"| 失败 | {report['failed']} |",
        f"| 平均分 | {report['average_score']:.2f} |",
        "",
        "## 各用例详情",
    ]

    for r in report.get("results", []):
        status = "✅" if r["passed"] else "❌"
        lines.append(f"\n### {status} {r['case_id']}: {r['case_name']}")
        lines.append(f"- **总分**: {r['overall_score']:.2f}")
        lines.append("- **规则检查**:")
        for rule, passed in r["rule_results"].items():
            r_status = "✅" if passed else ("❌" if passed is False else "⬜")
            lines.append(f"  - {r_status} {rule}")
        if r["warnings"]:
            lines.append("- **警告**:")
            for w in r["warnings"]:
                lines.append(f"  - ⚠️ {w}")

    return "\n".join(lines)


# ─── CLI 入口 ───
if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    cases = load_eval_cases()
    print(f"加载了 {len(cases)} 个评估用例")
    # 在 CLI 模式下只输出用例信息（实际评估需要真实 state）
    for c in cases:
        print(f"  - [{c['id']}] {c.get('name', c['id'])}")
    print("\n提示: 通过 orchestrator.propagate() 获取 state 后调用 run_evaluation()")
