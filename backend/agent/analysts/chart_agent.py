"""
Chart Agent — 数据可视化（ReAct 模式）

负责:
  拿到 SQL 查询结果 → 判断是否适合做图 → 双路径图表生成:
    - 快速路径: generate_chart 工具（简单柱状图/折线图/饼图）
    - 高质量路径: execute_python_code 工具（matplotlib 完整控制力）

ReAct 循环 (think → act → observe):
  1. 分析数据结构，判断适合什么图表类型
  2. 选择工具: generate_chart（快速）或 execute_python_code（高质量）
  3. 观察返回结果，验证图表正确性
  4. 如果图表有问题 → 调整参数重试

角色类比: 原项目的分析师（工具调用型 Agent）
LLM 策略: 使用 quick_think_llm（温度 0.1）

v3.2 改进（借鉴 data_analysis_agent）:
  - IPython 状态化代码执行环境: 变量跨代码块保持，LLM 可以迭代修改图表
  - matplotlib 完整控制力: 数据标签、自定义配色、参考线、多子图、双Y轴
  - YAML 结构化协议: LLM 输出 reasoning + code，YAML 多行字符串无需转义
  - 中文字体预配置 + Agg backend + 自动内存管理
"""

import json as _json
import logging
import uuid
from pathlib import Path

from backend.agent.utils.react import create_react_agent
from backend.agent.utils.state import DataAnalysisState
from backend.prompts import load_prompt
from backend.utils.yaml_parser import extract_yaml_and_code, parse_yaml_response

logger = logging.getLogger(__name__)

CHART_AGENT_SYSTEM_PROMPT = load_prompt("chart_agent")


def _try_yaml_fallback_chart(sql_result: str, llm_output: str = "") -> dict | None:
    """
    尝试从 YAML 格式的 LLM 输出中提取图表配置。

    借鉴 data_analysis_agent 的 YAML 协议:
      LLM 输出 YAML 格式（reasoning + chart_type + data），
      而非 JSON — YAML 多行字符串不需要转义引号，LLM 更容易产出正确的格式。

    期望格式:
      ```yaml
      reasoning: 数据适合用柱状图展示各产品销售额对比
      chart_type: bar
      x_column: 产品名
      y_column: 销售额
      title: 产品销售额对比
      ```

    Returns:
        解析成功返回 {chart_json, chart_config}，失败返回 None
    """
    meta, _code = extract_yaml_and_code(llm_output)

    if not meta:
        # 也尝试直接解析（无代码块的纯 YAML）
        meta = parse_yaml_response(llm_output)

    chart_type = str(meta.get("chart_type", "")).strip().lower()
    if not chart_type:
        return None

    x_column = str(meta.get("x_column", "")).strip()
    y_column = str(meta.get("y_column", "")).strip()
    title = str(meta.get("title", "")).strip()

    if not x_column or not y_column or not sql_result:
        return None

    # 从 SQL CSV 结果构造 data_json
    try:
        lines = [l for l in sql_result.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return None
        header = [h.strip() for h in lines[0].split(",")]
        rows = []
        for line in lines[1:51]:  # 最多 50 行
            values = [v.strip() for v in line.split(",")]
            if len(values) >= len(header):
                row_dict = {}
                for i, h in enumerate(header):
                    val = values[i]
                    try:
                        row_dict[h] = float(val)
                    except (ValueError, TypeError):
                        row_dict[h] = val
                rows.append(row_dict)

        if not rows:
            return None

        from backend.tools import generate_chart

        result = generate_chart.invoke({
            "chart_type": chart_type,
            "data_json": _json.dumps(rows, ensure_ascii=False),
            "title": title,
            "x_column": x_column,
            "y_column": y_column,
            "group_column": str(meta.get("group_column", "")) or None,
        })

        chart_content = result.content if hasattr(result, "content") else str(result)
        try:
            chart_json = _json.loads(chart_content)
            logger.info("[Chart Agent] YAML fallback 图表生成成功 (type=%s)", chart_type)
            return {
                "chart_json": chart_json,
                "chart_config": {
                    "title": title,
                    "chart_type": chart_type,
                    "x_axis": x_column,
                    "y_axis": y_column,
                },
            }
        except Exception:
            return None
    except Exception as e:
        logger.warning("[Chart Agent] YAML fallback 失败: %s", e)
        return None


# ═══════════════════════════════════════════════════════════
# 智能路径选择（v3.2）
# ═══════════════════════════════════════════════════════════

# 触发高质量路径的关键词
_HIGH_QUALITY_KEYWORDS = [
    "对比", "趋势", "标注", "定制", "双Y轴", "双轴", "子图",
    "参考线", "目标线", "高亮", "突出", "颜色", "配色",
    "数据标签", "环比", "同比", "占比", "堆叠", "分组",
    "热力图", "箱线图", "小提琴", "散点矩阵", "气泡",
    "详细", "美观", "专业", "精美", "高质量",
]

# 简单场景关键词（快速路径即可）
_FAST_PATH_KEYWORDS = [
    "简单", "快速", "粗略", "大致", "随便",
    "pie", "饼图", "占比(5类以内)",
]


def _recommend_chart_path(
    task_desc: str,
    sql_result: str,
    plan_expected_output: str = "",
) -> dict:
    """
    智能路由：分析任务+数据特征，推荐图表生成路径。

    借鉴 data_analysis_agent 的 action 路由设计:
      不是让 LLM 盲目选择工具，而是根据输入特征给出智能建议，
      LLM 可以覆盖建议但必须给出理由。

    Returns:
        {"path": "fast"|"high_quality"|"auto",
         "reason": "推荐理由",
         "prompt_hint": "注入 prompt 的提示文本"}
    """
    task_lower = (task_desc + " " + plan_expected_output).lower()

    # ─── 强制高质量：任务明确要求定制化 ───
    high_score = sum(1 for kw in _HIGH_QUALITY_KEYWORDS if kw in task_lower)
    if high_score >= 2:
        return {
            "path": "high_quality",
            "reason": f"任务包含 {high_score} 个高质量关键词",
            "prompt_hint": "**系统建议**: 任务涉及复杂可视化（关键词命中 {high_score} 个），请使用 `execute_python_code` 生成高质量图表。",
        }

    # ─── 强制快速：任务明确说简单 ───
    if any(kw in task_lower for kw in _FAST_PATH_KEYWORDS):
        return {
            "path": "fast",
            "reason": "任务标注为简单场景",
            "prompt_hint": "**系统建议**: 简单图表场景，使用 `generate_chart` 快速生成即可。",
        }

    # ─── 数据驱动判断 ───
    if sql_result and sql_result != "(无数据)":
        lines = [l for l in sql_result.strip().split("\n") if l.strip()]
        if len(lines) >= 2:
            header = [h.strip() for h in lines[0].split(",")]
            num_cols = 0
            try:
                row0 = lines[1].split(",")
                for val in row0:
                    try:
                        float(val.strip())
                        num_cols += 1
                    except ValueError:
                        pass
            except Exception:
                num_cols = 0

            # 多列数值 → 可能需要复杂可视化（双Y轴、子图、相关性）
            if num_cols >= 4:
                return {
                    "path": "high_quality",
                    "reason": f"数据有 {num_cols} 列数值，可能需要多子图或双Y轴",
                    "prompt_hint": f"**系统建议**: 数据包含 {num_cols} 个数值列，建议使用 `execute_python_code` 做多维度可视化。多个指标放在一个图里（双Y轴）或分面展示（多子图）效果更好。",
                }

            # 数据行数多 → gather_chart 足矣
            data_rows = len(lines) - 1
            if data_rows > 30:
                return {
                    "path": "fast",
                    "reason": f"数据有 {data_rows} 行，快速路径更稳定",
                    "prompt_hint": f"**系统建议**: 数据量较大（{data_rows} 行），使用 `generate_chart` 快速渲染更稳定。如需局部放大，建议先 SQL 聚合再画图。",
                }

            # 单列数值 + 单列分类 → 默认快速路径
            if num_cols == 1 and len(header) <= 3:
                return {
                    "path": "fast",
                    "reason": "单指标数据，快速路径即可",
                    "prompt_hint": "**系统建议**: 单指标数据，`generate_chart` 快速生成即可。如果你需要加数据标签或自定义配色，可以改用 `execute_python_code`。",
                }

    # ─── 默认：让 LLM 自行决定 ───
    return {
        "path": "auto",
        "reason": "无明显特征，LLM 自行判断",
        "prompt_hint": "系统未检测到特殊复杂度需求。简单图表用 `generate_chart`，需要定制化（数据标签/配色/参考线）用 `execute_python_code`。",
    }


def create_chart_agent(llm, tools):
    """
    创建 Chart Agent 节点函数（ReAct 模式）

    双路径图表生成:
      - 快速路径: generate_chart（固定参数 → Plotly JSON）
      - 高质量路径: execute_python_code（完整 matplotlib 控制力）

    Args:
        llm:   quick_think_llm 实例
        tools: [generate_chart, execute_python_code] 工具列表

    Returns:
        chart_agent_node(state) -> dict
    """

    def chart_agent_node(state: DataAnalysisState) -> dict:
        """LangGraph 节点函数"""
        plan = state.get("plan", [])
        task_desc = ""
        for s in plan:
            if s.get("type") == "chart":
                task_desc = s.get("task", "")
                break

        sql_result = state.get("sql_result", "")
        logger.info("[Chart Agent] 开始可视化，数据长度: %d", len(sql_result))

        # ─── 智能路径推荐 + 动态 prompt ───
        plan_expected = ""
        for s in plan:
            if s.get("type") == "chart":
                plan_expected = s.get("expected_output", "")
                break
        route = _recommend_chart_path(task_desc, sql_result, plan_expected)
        logger.info("[Chart Agent] 路径推荐: %s (原因: %s)", route["path"], route["reason"])

        dynamic_prompt = CHART_AGENT_SYSTEM_PROMPT.replace(
            "## 当前任务步骤",
            f"{route['prompt_hint']}\n\n## 当前任务步骤",
        )
        # 创建本次调用的 ReAct agent（使用动态 prompt，包含路径推荐）
        call_react = create_react_agent(
            llm=llm,
            tools=tools,
            system_prompt=dynamic_prompt,
            max_iterations=5,
        )

        # ─── 初始化 CodeExecutor（v3.2） ───
        session_id = state.get("_session_id") or uuid.uuid4().hex[:12]
        session_dir = state.get("_session_dir") or f"output/session_{session_id}"
        try:
            from backend.tools.code_executor import get_executor, reset_executor
            # 每次分析重置执行器，确保图表保存到当前会话目录
            reset_executor()
            # 参考 data_analysis_agent: 图表和报告同目录，用相对路径
            executor = get_executor(session_dir=str(Path(session_dir)))
            if sql_result and sql_result != "(无数据)":
                try:
                    lines = [l.strip() for l in sql_result.strip().split("\n") if l.strip()]
                    if len(lines) >= 2:
                        header = [h.strip() for h in lines[0].split(",")]
                        rows = []
                        for line in lines[1:101]:
                            vals = [v.strip() for v in line.split(",")]
                            if len(vals) >= len(header):
                                row_dict = {}
                                for i, h in enumerate(header):
                                    val = vals[i]
                                    try:
                                        row_dict[h] = float(val)
                                    except (ValueError, TypeError):
                                        row_dict[h] = val
                                rows.append(row_dict)
                        if rows:
                            executor.set_variable("sql_header", header)
                            executor.set_variable("sql_rows", rows)
                            executor._exec(
                                "import pandas as pd\n"
                                f"sql_data = pd.DataFrame({rows!r}, columns={header!r})"
                            )
                            logger.info("[Chart Agent] sql_data DataFrame 已注入 (%d行)", len(rows))
                except Exception as e:
                    logger.warning("[Chart Agent] sql_data 注入失败: %s", e)
        except Exception as e:
            logger.warning("[Chart Agent] CodeExecutor 初始化失败: %s", e)

        # 注入运行时参数
        enriched_state = dict(state)
        enriched_state["current_task"] = task_desc or "根据数据生成合适的图表"
        enriched_state["sql_result"] = sql_result[:2000] if sql_result else "(无数据)"
        enriched_state["_chart_path"] = route["path"]

        # 执行 ReAct 循环
        result = call_react(enriched_state)

        # DEBUG: log chart agent activity
        import datetime as _dt
        with open("debug_chart.log", "a", encoding="utf-8") as df:
            df.write(f"{_dt.datetime.now()} [Chart Agent] react done: {result.get('react_iterations',0)} rounds, {len(result.get('react_tool_calls',[]))} tool calls\n")
            for tc in result.get("react_tool_calls", []):
                df.write(f"  tool={tc['tool']} result_preview={tc.get('result_preview','')[:200]}\n")

        # ═══ 提取图表结果（仅 execute_python_code 路径） ═══
        chart_files: list[str] = []

        for call in result.get("react_tool_calls", []):
            tool_name = call["tool"]
            rp = call.get("result_preview", "")

            if tool_name == "execute_python_code":
                # 从 stdout 中提取图片路径
                if not rp.startswith("ERROR"):
                    import re
                    # 匹配 "图片已保存: D:\path\to\file.png" 格式
                    found = re.findall(r'(?:图片已保存|file_path|保存至)[:\s]*(\S+\.png)', rp)
                    if not found:
                        found = re.findall(r'([A-Za-z]:\\\S+\.png)', rp)
                    if not found:
                        found = re.findall(r'(/\S+\.png)', rp)
                    chart_files.extend(found)
                    logger.info("[Chart Agent] execute_python_code → %d PNG", len(found))

        logger.info(
            "[Chart Agent] ReAct: %d rounds, %d tool calls, PNG=%d",
            result.get("react_iterations", 0),
            len(result.get("react_tool_calls", [])),
            len(chart_files),
        )

        # DEBUG
        import datetime as _dt2
        with open("debug_chart.log", "a", encoding="utf-8") as df:
            df.write(f"{_dt2.datetime.now()} FINAL: chart_files={chart_files}\n")

        # 自动推进步骤
        current_step = state.get("current_step_index", 0)
        plan = state.get("plan", [])
        next_step_idx = current_step + 1
        step_advance = {}
        if next_step_idx < len(plan):
            step_advance = {"current_step_index": next_step_idx}

        out = {
            **step_advance,
            "messages": result["messages"],
            "progress_message": "Chart Agent: chart generation complete",
            "react_iterations": result.get("react_iterations", 0),
            "react_tool_calls": result.get("react_tool_calls", []),
            "react_intermediate_steps": result.get("react_intermediate_steps", []),
        }
        if chart_files:
            out["chart_files"] = chart_files
        return out

    return chart_agent_node
