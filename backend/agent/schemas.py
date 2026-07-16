"""
LLM 输出 Schema — 为关键 Agent 提供 Pydantic 类型化输出。

每个 Schema 通过 llm.with_structured_output() 使用，确保 LLM 输出是确定性的
类型化数据，消除 free-text JSON 解析的脆弱性。

参考: tradingagents/agents/schemas.py → PortfolioRating, ResearchPlan 等

设计:
  - 字段级 description 成为 LLM 的输出指令
  - 宽松的默认值确保弱模型输出不会导致解析崩溃
  - 所有 Schema 与现有 state dict keys 向后兼容
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from backend.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Validator
# ═══════════════════════════════════════════════════════════


class ValidationResult(BaseModel):
    """Validator 输出 — 报告裁判结果"""

    result: Literal["approved", "rejected", "needs_review"] = Field(
        description="裁判结论: approved(通过) / rejected(驳回修正) / needs_review(需人工审核)"
    )
    reason: str = Field(
        description="裁判理由，至少 20 字，说明为什么通过/驳回/需要人工审核"
    )
    revise_suggestions: str = Field(
        default="",
        description="如果驳回，给出具体修改建议；如果通过则为空",
    )


# ═══════════════════════════════════════════════════════════
# Debate Scorer
# ═══════════════════════════════════════════════════════════


class DebateScoreBreakdown(BaseModel):
    """单方评分子项"""

    argument_quality: int = Field(
        default=0, ge=0, le=40, description="论据质量得分 (0-40)"
    )
    data_support: int = Field(
        default=0, ge=0, le=40, description="数据支撑得分 (0-40)"
    )
    rebuttal: int = Field(
        default=0, ge=0, le=20, description="反驳力度得分 (0-20)"
    )


class DebateScoreResult(BaseModel):
    """Debate Scorer 输出 — 辩论评分结果"""

    optimistic_score: int = Field(
        default=50, ge=0, le=100, description="正方(乐观方)总分 0-100"
    )
    pessimistic_score: int = Field(
        default=50, ge=0, le=100, description="反方(谨慎方)总分 0-100"
    )
    optimistic_breakdown: DebateScoreBreakdown = Field(
        default_factory=DebateScoreBreakdown, description="正方分项得分"
    )
    pessimistic_breakdown: DebateScoreBreakdown = Field(
        default_factory=DebateScoreBreakdown, description="反方分项得分"
    )
    optimistic_strengths: str = Field(
        default="", description="正方论据的优点"
    )
    optimistic_weaknesses: str = Field(
        default="", description="正方论据的不足"
    )
    pessimistic_strengths: str = Field(
        default="", description="反方论据的优点"
    )
    pessimistic_weaknesses: str = Field(
        default="", description="反方论据的不足"
    )
    winner: Literal["optimistic", "pessimistic", "tie"] = Field(
        default="tie", description="辩论胜方"
    )
    summary: str = Field(
        default="", description="辩论评分总结，至少 10 字"
    )


# ═══════════════════════════════════════════════════════════
# Planner
# ═══════════════════════════════════════════════════════════


class PlanStep(BaseModel):
    """单个执行步骤"""

    step: int = Field(ge=1, description="步骤序号，从1开始")
    task: str = Field(description="步骤任务描述")
    type: Literal["sql", "chart", "finalize"] = Field(
        description="步骤类型: sql(数据查询) / chart(图表生成) / finalize(分析终止，触发报告生成)"
    )
    depends_on: list[int] = Field(
        default_factory=list, description="此步骤依赖的前序步骤编号"
    )
    expected_output: str = Field(
        default="", description="此步骤预期产出的描述"
    )


class PlanResult(BaseModel):
    """Planner 输出 — 任务拆解计划"""

    plan: list[PlanStep] = Field(
        description="执行步骤列表，最多5步", min_length=1, max_length=5
    )


# ═══════════════════════════════════════════════════════════
# 结构化输出包装器
# ═══════════════════════════════════════════════════════════


def try_structured_output(
    llm,
    model_cls: type[BaseModel],
    prompt,
    invoke_args: dict,
    description: str = "Agent",
) -> dict:
    """
    尝试 structured output，失败时降级到 free-text + parse_llm_json。

    如果 provider 支持 structured output（DeepSeek、OpenAI 等通过
    json_schema/response_format 实现），直接返回类型化 dict。
    否则降级到普通 invoke + JSON 解析。

    Args:
        llm:          LLM 实例
        model_cls:    Pydantic BaseModel 子类
        prompt:       ChatPromptTemplate 实例
        invoke_args:  传给 prompt 的模板变量 dict
        description:  日志描述

    Returns:
        dict — model_cls.model_dump() 的结果，或解析后的 dict
    """
    try:
        structured_llm = llm.with_structured_output(model_cls, method="json_schema")
        structured_chain = prompt | structured_llm
        result = structured_chain.invoke(invoke_args)
        if isinstance(result, model_cls):
            return result.model_dump()
        # 某些 langchain 版本可能返回 dict
        if isinstance(result, dict):
            return model_cls.model_validate(result).model_dump()
        raise TypeError(f"Unexpected structured output type: {type(result).__name__}")
    except (AttributeError, NotImplementedError, TypeError) as e:
        logger.warning(
            "[%s] Structured output 不可用 (%s)，降级到 free-text 解析",
            description,
            e,
        )
    except Exception as e:
        logger.warning(
            "[%s] Structured output 调用失败 (%s)，降级到 free-text 解析",
            description,
            e,
        )

    # ─── Fallback: free-text + JSON 解析 ───
    try:
        chain = prompt | llm
        response = chain.invoke(invoke_args)
        content = response.content if hasattr(response, "content") else str(response)
        parsed = parse_llm_json(content, description=description)
        # 尝试验证并转换为目标模型
        try:
            return model_cls.model_validate(parsed).model_dump()
        except Exception:
            # 宽松返回 — 调用方需要自行处理可能缺少的字段
            return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        logger.error("[%s] 所有解析路径均失败: %s", description, e)
        # 返回默认构造的 dict
        try:
            return model_cls().model_dump()
        except Exception:
            return {}


# ═══════════════════════════════════════════════════════════
# 结构化渲染函数（v3.3 — 借鉴 TradingAgents 的 render_*()）
#
# TradingAgents 的核心设计: Pydantic 实例 → 确定性 Markdown
#   无论用什么 LLM provider，最终报告格式都不会漂移。
#   结构化输出保证字段一致，render_*() 保证渲染格式一致。
# ═══════════════════════════════════════════════════════════


def render_plan(plan: list[dict]) -> str:
    """渲染执行计划为 Markdown。"""
    if not plan:
        return "*无执行计划*"

    type_emoji = {"sql": "🔍", "chart": "📊", "finalize": "📝"}
    lines = ["| 步骤 | 类型 | 任务 | 依赖 |", "|------|------|------|------|"]
    for s in plan:
        emoji = type_emoji.get(s.get("type", ""), "❓")
        deps = ", ".join(str(d) for d in s.get("depends_on", [])) or "—"
        lines.append(
            f"| {s.get('step', '?')} | {emoji} {s.get('type', '?')} "
            f"| {s.get('task', '')[:60]} | {deps} |"
        )
    return "\n".join(lines)


def render_validation(result: dict) -> str:
    """渲染 Validator 结果为 Markdown。"""
    if not result:
        return "*未验证*"

    status = result.get("result", "unknown")
    reason = result.get("reason", "")
    suggestions = result.get("revise_suggestions", "")

    emoji_map = {
        "approved": "✅",
        "rejected": "❌",
        "needs_review": "⚠️",
    }
    emoji = emoji_map.get(status, "❓")

    lines = [f"**验证结果**: {emoji} {status}", ""]
    if reason:
        lines.append(f"**理由**: {reason}")
    if suggestions:
        lines.append(f"**修改建议**: {suggestions}")
    return "\n".join(lines)


def render_debate_scores(scores: dict) -> str:
    """渲染辩论评分为 Markdown。"""
    if not scores:
        return "*无辩论评分*"

    winner = scores.get("winner", "tie")
    winner_label = {"optimistic": "🔵 正方胜", "pessimistic": "🔴 反方胜", "tie": "⚪ 平局"}

    lines = [
        f"## 辩论评分: {winner_label.get(winner, winner)}",
        "",
        "| 评分维度 | 正方（乐观） | 反方（谨慎） |",
        "|----------|-------------|-------------|",
    ]

    opt_break = scores.get("optimistic_breakdown", {})
    pes_break = scores.get("pessimistic_breakdown", {})

    for key, label in [("argument_quality", "论据质量"), ("data_support", "数据支撑"), ("rebuttal", "反驳力度")]:
        lines.append(
            f"| {label} | {opt_break.get(key, 0)} | {pes_break.get(key, 0)} |"
        )

    lines.append(
        f"| **总分** | **{scores.get('optimistic_score', 0)}** "
        f"| **{scores.get('pessimistic_score', 0)}** |"
    )
    lines.append("")

    summary = scores.get("summary", "")
    if summary:
        lines.append(f"**总结**: {summary}")
    return "\n".join(lines)


def render_chart_section(
    chart_json: dict | None,
    chart_files: list[str] | None = None,
    for_html: bool = False,
) -> str:
    """渲染图表引用为 Markdown 或 HTML。

    如果 chart_files 中有实际的 PNG 文件 → 用 ![](path) 引用
    如果只有 chart_json（Plotly）→ 对于 HTML 嵌入交互式图表，MD 生成 base64 降级

    Args:
        chart_json:   Plotly Figure JSON
        chart_files:  PNG 文件路径列表（matplotlib 代码执行产物）
        for_html:     是否生成 HTML 嵌入代码（而非 Markdown）
    """
    lines = []

    if for_html and chart_json and isinstance(chart_json, dict) and "data" in chart_json:
        # HTML 报告：嵌入交互式 Plotly 图表
        import json
        chart_id = f"chart_{hash(json.dumps(chart_json, sort_keys=True, default=str)) % 100000}"
        chart_json_str = json.dumps(chart_json, ensure_ascii=False)
        lines.append(
            f'<div id="{chart_id}" style="width:100%; min-height:450px;"></div>\n'
            f"<script>\n"
            f"  (function() {{\n"
            f"    var data = {chart_json_str};\n"
            f"    if (typeof Plotly !== 'undefined') {{\n"
            f"      Plotly.newPlot('{chart_id}', data.data, data.layout || {{}}, {{responsive: true}});\n"
            f"    }} else {{\n"
            f"      document.getElementById('{chart_id}').innerHTML = "
            f"'<p style=\"color:#999;padding:40px;text-align:center\">"
            f"[Chart data available — open in browser with Plotly.js]</p>';\n"
            f"    }}\n"
            f"  }})();\n"
            f"</script>"
        )
    elif chart_json and isinstance(chart_json, dict):
        # Markdown/DOCX 报告：提示 + 尝试 base64 PNG 降级
        lines.append("### 📊 交互式图表")
        base64_png = _plotly_to_base64_png(chart_json)
        if base64_png:
            lines.append(f"![图表]({base64_png})")
        else:
            lines.append("*（Plotly 交互式图表 — 请在浏览器中打开 HTML 报告查看）*")
        lines.append("")

    if chart_files:
        lines.append("### 🖼️ 图表文件")
        for f in chart_files:
            import os
            name = os.path.basename(f)
            if for_html:
                # HTML 中如果有实际 PNG，生成 img 标签
                lines.append(f'<img src="./charts/{name}" alt="{name}" style="max-width:100%;">')
            else:
                lines.append(f"![{name}](./{name})")
        lines.append("")

    return "\n".join(lines) if len(lines) > 1 else ""


def _plotly_to_base64_png(chart_json: dict) -> str | None:
    """将 Plotly JSON 转为 base64 PNG（用于 MD/DOCX 中嵌入图表）。

    需要 kaleido 或 plotly-orca。不可用时返回 None。
    """
    try:
        import plotly.io as pio
        import base64
        fig = pio.from_json(chart_json) if isinstance(chart_json, str) else pio.from_json(
            __import__('json').dumps(chart_json)
        )
        img_bytes = fig.to_image(format="png", width=800, height=450, scale=1)
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except (ImportError, Exception):
        return None


def render_sql_section(sql_query: str, sql_result: str) -> str:
    """渲染 SQL 查询与结果为 Markdown。"""
    if not sql_query and not sql_result:
        return ""

    lines = []
    if sql_query:
        lines.extend(["### 🔍 SQL 查询", "", "```sql", sql_query.strip(), "```", ""])
    if sql_result:
        result_preview = sql_result[:2000]
        if len(sql_result) > 2000:
            result_preview += "\n\n*(结果已截断)*"
        lines.extend(["### 📋 查询结果", "", "```csv", result_preview.strip(), "```", ""])
    return "\n".join(lines)


def render_performance(performance: dict | None) -> str:
    """渲染性能指标为 Markdown。"""
    if not performance:
        return ""

    lines = [
        "## ⏱️ 性能统计",
        "",
        f"- 总耗时: **{performance.get('total_time', 0):.1f} 秒**",
        f"- 执行节点: **{performance.get('node_count', 0)} 个**",
        f"- 平均节点耗时: **{performance.get('average_node_time', 0):.2f} 秒**",
    ]

    if performance.get("node_timings"):
        lines.append("")
        lines.append("| 节点 | 耗时 |")
        lines.append("|------|------|")
        for name, t in sorted(performance["node_timings"].items(), key=lambda x: -x[1]):
            lines.append(f"| {name} | {t:.1f}s |")

    return "\n".join(lines)
