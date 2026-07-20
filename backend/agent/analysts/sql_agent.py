"""
SQL Agent — 自然语言转SQL并执行（ReAct 模式）

负责:
  拿到任务描述 → 理解表结构 → 生成 SQL → 调用工具执行 → 观察结果 → 修正或完成

ReAct 循环 (think → act → observe):
  1. 分析任务和表结构，决定是否需要先查看表数据
  2. 调用 get_table_info / execute_sql 获取信息
  3. 观察返回结果，判断 SQL 是否正确
  4. 如果正确 → 输出最终结果
  5. 如果错误 → 分析原因 → 修正 SQL → 重试（最多 5 轮）

角色类比: 原项目的 分析师四兄弟（工具调用型 Agent）
LLM 策略: 使用 quick_think_llm（温度 0.1），需要精准的 SQL 生成
"""

import logging

from backend.agent.utils.react import create_react_agent
from backend.agent.utils.state import DataAnalysisState
from backend.prompts import load_prompt

logger = logging.getLogger(__name__)

SQL_AGENT_SYSTEM_PROMPT = load_prompt("sql_agent")


def create_sql_agent(llm, tools, store=None):
    """
    创建 SQL Agent 节点函数（ReAct 模式）


    v3.0 改进:
      - 支持 store 参数：预取表结构和示例数据，注入 prompt，跳过 get_table_info 调用
      - 减少 1-2 轮无效工具调用

    Args:
        llm:   quick_think_llm 实例
        tools: [get_table_info, execute_sql, validate_sql] 工具列表
        store: 可选的 SQLiteStore 实例（用于预取表结构）

    Returns:
        sql_agent_node(state) -> dict
    """
    react_node = create_react_agent(
        llm=llm,
        tools=tools,
        system_prompt=SQL_AGENT_SYSTEM_PROMPT,
        max_iterations=5,
    )

    def sql_agent_node(state: DataAnalysisState) -> dict:
        """LangGraph 节点函数"""
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)

        # 确定当前任务
        if current_step < len(plan):
            task_desc = plan[current_step].get("task", state["user_query"])
        else:
            task_desc = state["user_query"]

        is_retry = bool(state.get("sql_error", ""))
        logger.info("[SQL Agent] 执行步骤 %d/%d: %s%s", current_step + 1, len(plan), task_desc[:80],
                     " (重试)" if is_retry else "")

        # 构建计划上下文
        plan_lines = []
        for i, s in enumerate(plan):
            marker = "→ " if i == current_step else "  "
            status = ""
            if i < current_step:
                status = " ✅"
            plan_lines.append(f"{marker}第{s.get('step', i+1)}步: {s.get('task', '')}{status}")
        plan_context = "\n".join(plan_lines)

        # 构建前序步骤结果（重试时不注入错误结果，避免 LLM 放弃重试）
        prev_results_parts = []
        prev_sql_error = state.get("sql_error", "")
        if not prev_sql_error:
            prev_sql_result = state.get("sql_result", "")
            if prev_sql_result and prev_sql_result != "(查询成功，但无返回数据)":
                prev_results_parts.append(f"前序SQL结果:\n{prev_sql_result[:800]}")

        prev_chart = state.get("chart_json")
        if prev_chart:
            prev_results_parts.append("(前序步骤已生成图表)")

        previous_results = "\n\n".join(prev_results_parts) if prev_results_parts else "(这是第一个步骤)"

        # 注入运行时参数到 state（供 ReAct agent 的 prompt 模板使用）
        enriched_state = dict(state)
        enriched_state["plan_context"] = plan_context
        enriched_state["current_task"] = task_desc
        enriched_state["previous_results"] = previous_results

        # ─── 预取表结构（v3.0） ───
        pre_fetched_schemas = state.get("table_schemas_text", "")
        if store and (not pre_fetched_schemas or len(pre_fetched_schemas) < 50):
            try:
                available_tables = state.get("available_tables", [])
                tables = available_tables if available_tables else store.get_tables()
                schema_parts = []
                for t in tables[:3]:  # 最多3张表
                    info = store.get_schema(t)
                    if info:
                        cols = ", ".join(f"{c['name']}({c['type']})" for c in info)
                        preview = store.preview(t, limit=3)
                        schema_parts.append(f"**表: {t}**\n列: {cols}\n示例数据(前3行):\n{preview}")
                if schema_parts:
                    pre_fetched_schemas = "\n\n".join(schema_parts)
                    logger.info("[SQL Agent] 预取 %d 张表结构，跳过 get_table_info", len(tables))
            except Exception as e:
                logger.warning("[SQL Agent] 预取表结构失败: %s，Agent 将通过工具获取", e)

        # 注入预取的表结构（如果已预取则加提示，否则使用 state 中原有的）
        if pre_fetched_schemas and len(pre_fetched_schemas) > 50:
            enriched_state["table_schemas"] = (
                "注意：以下表结构已预先获取，直接编写 SQL，无需调用 get_table_info。\n\n"
                + pre_fetched_schemas
            )
        else:
            enriched_state["table_schemas"] = pre_fetched_schemas

        # 重试时清除历史消息，给 LLM 一个干净的开始
        if is_retry:
            enriched_state["messages"] = []

        # 执行 ReAct 循环
        result = react_node(enriched_state)

        # 提取 SQL 相关的数据写入 state
        sql_queries = []
        sql_results = []
        sql_error = ""

        for call in result.get("react_tool_calls", []):
            if call["tool"] == "execute_sql":
                sql = call["args"].get("sql", "")
                if sql:
                    sql_queries.append(sql)
                rp = call.get("result_preview", "")
                if rp.startswith("ERROR:"):
                    if not sql_error:
                        sql_error = rp
                elif len(rp) > 5:
                    sql_results.append(rp)

        combined_sql = "\n\n".join(sql_queries[-5:])
        combined_result = "\n\n".join(sql_results[-5:])

        retry_count = state.get("sql_retry_count", 0)
        if sql_error:
            retry_count += 1

        logger.info(
            "[SQL Agent] ReAct: %d轮, %d次工具调用, %d条SQL, 错误=%s",
            result.get("react_iterations", 0),
            len(result.get("react_tool_calls", [])),
            len(sql_queries),
            bool(sql_error),
        )

        # 自动推进步骤 — SQL Agent 完成后始终推进到下一步
        # should_continue_sql 会检查 plan[current_step] 决定路由方向
        next_step_idx = current_step + 1
        step_advance = {}
        if next_step_idx < len(plan):
            step_advance = {
                "current_step_index": next_step_idx,
            }

        return {
            **step_advance,
            "messages": result["messages"],
            "sql_query": combined_sql,
            "sql_result": combined_result if not sql_error else combined_result,
            "sql_error": sql_error,
            "sql_retry_count": retry_count if sql_error else state.get("sql_retry_count", 0),
            "progress_message": step_advance.get("progress_message",
                f"SQL Agent: {task_desc[:80]}... ({result.get('react_iterations', 0)} round reasoning)"),
            "react_intermediate_steps": result.get("react_intermediate_steps", []),
            "react_iterations": result.get("react_iterations", 0),
            "react_tool_calls": result.get("react_tool_calls", []),
        }

    return sql_agent_node
