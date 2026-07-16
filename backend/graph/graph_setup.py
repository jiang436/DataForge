"""
GraphSetup — 构建 LangGraph 工作流

参考: tradingagents/graph/setup.py → GraphSetup.setup_graph()

图结构（ReAct 模式下，ToolNode 作为后备）:
  START → Planner → SQL Agent (ReAct) ←→ tools_sql (后备) → Msg Clear SQL
         → Chart Agent (ReAct) ←→ tools_chart (后备) → Msg Clear Chart
         → Report Agent → Optimistic ↔ Pessimistic (辩论循环)
         → Validator → END / Report Agent (驳回修正)

v3.1 改进:
  - 显式 Action 状态机: Planner 引入 type=finalize，自动终止分析
  - 简单模式 (mode="simple"): 跳过辩论和评估，快速出结果
  - Report Agent 独立高 token LLM (16384)，长报告不截断
  - 步骤自动推进: 每个 Agent 完成后自动 current_step_index += 1

ReAct 模式说明:
  每个 Agent 内部封装了 think→act→observe 循环。
  ToolNode 作为后备：如果 Agent 返回了 tool_calls（极少情况），LangGraph 仍会执行。
"""

import logging

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.agent.analysts.chart_agent import create_chart_agent
from backend.agent.analysts.sql_agent import create_sql_agent
from backend.agent.debaters.optimist import create_optimist
from backend.agent.debaters.pessimist import create_pessimist
from backend.agent.managers.planner import create_planner
from backend.agent.managers.validator import create_validator
from backend.agent.synthesis.report_agent import create_report_agent
from backend.agent.utils.state import DataAnalysisState
from backend.graph.conditional_logic import ConditionalLogic
from backend.llm_clients import create_llm
from backend.tools import CHART_TOOLS, SQL_TOOLS

logger = logging.getLogger(__name__)


def _create_step_advancer():
    """
    步骤推进节点 — 每个 Agent 完成后自动推进 current_step_index。

    借鉴 data_analysis_agent 的显式 action 循环:
      每完成一步后 current_step += 1，系统自动判断下一步做什么，
      而非依赖 LLM 自行决定何时停止。
    """

    def advance_step(state: DataAnalysisState) -> dict:
        current = state.get("current_step_index", 0)
        plan = state.get("plan", [])
        next_idx = current + 1

        if next_idx < len(plan):
            next_step = plan[next_idx]
            logger.info("[步骤推进] %d → %d, 下一步: %s (type=%s)",
                        current, next_idx, next_step.get("task", "")[:60], next_step.get("type", "sql"))
            return {
                "current_step_index": next_idx,
                "progress_message": f"Execute step {next_idx + 1}/{len(plan)}: {next_step.get('task', '')[:60]}",
            }

        logger.info("[步骤推进] 所有 %d 步已完成, idx=%d", len(plan), next_idx)
        return {"current_step_index": next_idx}

    return advance_step


def _create_msg_clear():
    """
    消息清理节点

    参考: tradingagents/agents/__init__.py → create_msg_delete()
    每个 Agent 完成后清理消息，避免 token 不断膨胀。

    ReAct 模式下，每个 Agent 节点内部会产生多条消息（思考→工具调用→观察→...）。
    Msg Clear 将这些中间消息清除，注入上下文锚点，防止 "Continue" literal bug
    （某些 provider 看到 "Continue" 会字面量执行而非理解为 "继续下一步"）。
    """
    from langchain_core.messages import HumanMessage, RemoveMessage

    def clear(state: DataAnalysisState) -> dict:
        messages = state.get("messages", [])
        user_query = state.get("user_query", "")
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)

        # ─── 构建上下文锚点 ───
        context_parts = [f"用户原始问题: {user_query[:200]}"]

        # 计划进度
        if plan:
            total = len(plan)
            done_count = min(current_step, total)
            context_parts.append(f"执行进度: {done_count}/{total} 步已完成")

            # 关键中间结果
            sql_result = state.get("sql_result", "")
            if sql_result:
                snippet = sql_result[:300].replace("\n", " ")
                context_parts.append(f"上一步SQL结果摘要: {snippet}")

            chart_json = state.get("chart_json")
            if chart_json:
                context_parts.append("图表已生成")

            draft_report = state.get("draft_report", "")
            if draft_report:
                context_parts.append(f"报告草稿(前200字): {draft_report[:200]}")

            # 下一步任务
            if current_step < total:
                next_task = plan[current_step].get("task", "")
                context_parts.append(f"下一步任务: {next_task}")

        context = "\n".join(context_parts)

        removal = [RemoveMessage(id=m.id) for m in messages if hasattr(m, "id")]
        logger.debug(
            "Msg Clear: 清理 %d 条中间消息, 注入上下文 (%d 字符)",
            len(removal), len(context),
        )
        return {"messages": removal + [HumanMessage(content=context)]}

    return clear


class GraphSetup:
    """
    图构建器

    参考: tradingagents/graph/setup.py → GraphSetup 类

    ReAct 模式关键变更:
      - SQL/Chart Agent 使用 ReAct 循环（内置工具调用）
      - ToolNode 保留作为后备（Agent 返回未处理的 tool_calls 时）
      - 条件路由简化：ReAct Agent 通常直接进入 Msg Clear

    v3.1 新增:
      - mode="simple": 跳过辩论和评估，快速出结果
      - Planner→xxx 路由: 支持 finalize 步骤的显式终止
      - Report Agent 高 token LLM: 16384 max_tokens，长报告不截断
    """

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        conditional_logic: ConditionalLogic,
        provider: str = "deepseek",
        mode: str = "full",
    ):
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.conditional_logic = conditional_logic
        self.provider = provider
        self.mode = mode  # "full" | "simple"

        # ─── Report Agent 独立高 token LLM ───
        # 借鉴 data_analysis_agent: 报告阶段使用 max_tokens=16384
        # （分析阶段的 2-4 倍），确保长报告不被截断
        try:
            self.report_llm = create_llm(
                provider=provider,
                temperature=0.3,
                max_tokens=16384,
            )
            logger.info("Report Agent LLM: max_tokens=16384 (独立高 token 限制)")
        except Exception as e:
            logger.warning("Report Agent 高 token LLM 创建失败，使用 deep_llm: %s", e)
            self.report_llm = deep_thinking_llm

    def setup_graph(self):
        """构建并编译 LangGraph 工作流"""
        mode_label = "简单模式" if self.mode == "simple" else "完整模式"
        logger.info("=" * 60)
        logger.info("GraphSetup: 构建 LangGraph 工作流 (ReAct + %s)", mode_label)
        logger.info("=" * 60)

        # ─── 工具节点（后备） ───
        tools_sql = ToolNode(list(SQL_TOOLS))
        tools_chart = ToolNode(list(CHART_TOOLS))

        # ─── Agent 节点 ───
        msg_clear = _create_msg_clear()
        step_advancer = _create_step_advancer()

        planner_node = create_planner(self.deep_thinking_llm)
        # SQL Agent: 尝试获取 store 引用用于预取表结构（减少工具调用）
        try:
            from backend.tools import get_store as tools_get_store
            _store = tools_get_store()
        except Exception:
            _store = None
        sql_agent_node = create_sql_agent(self.quick_thinking_llm, list(SQL_TOOLS), store=_store)
        chart_agent_node = create_chart_agent(self.quick_thinking_llm, list(CHART_TOOLS))
        # Report Agent: 使用独立高 token LLM（16384），长报告不截断
        report_agent_node = create_report_agent(self.report_llm)

        # ─── StateGraph ───
        wf = StateGraph(DataAnalysisState)

        wf.add_node("Planner", planner_node)
        wf.add_node("SQL Agent", sql_agent_node)
        wf.add_node("tools_sql", tools_sql)
        wf.add_node("Msg Clear SQL", msg_clear)
        wf.add_node("Step Advance SQL", step_advancer)
        wf.add_node("Chart Agent", chart_agent_node)
        wf.add_node("tools_chart", tools_chart)
        wf.add_node("Msg Clear Chart", msg_clear)
        wf.add_node("Step Advance Chart", step_advancer)
        wf.add_node("Report Agent", report_agent_node)

        # 简单模式跳过的节点
        if self.mode != "simple":
            optimist_node = create_optimist(self.quick_thinking_llm)
            pessimist_node = create_pessimist(self.quick_thinking_llm)
            validator_node = create_validator(self.deep_thinking_llm)
            wf.add_node("Optimistic", optimist_node)
            wf.add_node("Pessimistic", pessimist_node)
            wf.add_node("Validator", validator_node)

        total_nodes = 11 + (0 if self.mode == "simple" else 3)
        logger.info("已添加 %d 个节点 (mode=%s)", total_nodes, self.mode)

        # ═══════════════════════════════════════════════
        # 编排边
        # ═══════════════════════════════════════════════

        # START → Planner → 显式路由
        wf.add_edge(START, "Planner")
        wf.add_conditional_edges(
            "Planner",
            self.conditional_logic.should_continue_after_planner,
            {
                "SQL Agent": "SQL Agent",
                "Chart Agent": "Chart Agent",
                "Report Agent": "Report Agent",
                "END": END,
            },
        )

        # SQL Agent → 执行工具 / 重试 / 清理消息
        wf.add_conditional_edges(
            "SQL Agent",
            self.conditional_logic.should_continue_sql,
            {
                "tools_sql": "tools_sql",
                "Msg Clear SQL": "Msg Clear SQL",
                "SQL Agent": "SQL Agent",
                "Chart Agent": "Chart Agent",
                "Report Agent": "Report Agent",
            },
        )
        wf.add_edge("tools_sql", "SQL Agent")
        # Msg Clear SQL → 步骤推进 → 显式路由
        wf.add_edge("Msg Clear SQL", "Step Advance SQL")
        wf.add_conditional_edges(
            "Step Advance SQL",
            self.conditional_logic.should_continue_after_sql,
            {
                "Chart Agent": "Chart Agent",
                "SQL Agent": "SQL Agent",
                "Report Agent": "Report Agent",
            },
        )

        # Chart Agent → 执行工具 / 清理消息
        wf.add_conditional_edges(
            "Chart Agent",
            self.conditional_logic.should_continue_chart,
            {
                "tools_chart": "tools_chart",
                "Msg Clear Chart": "Msg Clear Chart",
                "SQL Agent": "SQL Agent",
                "Report Agent": "Report Agent",
            },
        )
        wf.add_edge("tools_chart", "Chart Agent")
        # Msg Clear Chart → 步骤推进 → 显式路由
        wf.add_edge("Msg Clear Chart", "Step Advance Chart")
        wf.add_conditional_edges(
            "Step Advance Chart",
            self.conditional_logic.should_continue_after_chart,
            {
                "SQL Agent": "SQL Agent",
                "Chart Agent": "Chart Agent",
                "Report Agent": "Report Agent",
            },
        )

        if self.mode == "simple":
            # ─── 简单模式: Report Agent → END ───
            logger.info("[GraphSetup] 简单模式: 跳过辩论和评估")
            wf.add_edge("Report Agent", END)
        else:
            # ─── 完整模式: Report → 辩论 → Validator → END/驳回 ───
            wf.add_conditional_edges(
                "Report Agent",
                self.conditional_logic.should_continue_after_report,
                {"Optimistic": "Optimistic", "Validator": "Validator"},
            )
            wf.add_conditional_edges(
                "Optimistic",
                self.conditional_logic.should_continue_debate,
                {"Pessimistic": "Pessimistic", "Validator": "Validator"},
            )
            wf.add_conditional_edges(
                "Pessimistic",
                self.conditional_logic.should_continue_debate,
                {"Optimistic": "Optimistic", "Validator": "Validator"},
            )
            wf.add_conditional_edges(
                "Validator",
                self.conditional_logic.should_continue_after_validator,
                {"END": END, "Report Agent": "Report Agent"},
            )

        compiled = wf.compile()
        logger.info("GraphSetup: 编译完成 (mode=%s)", self.mode)
        return compiled
