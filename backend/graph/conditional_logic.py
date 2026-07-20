"""
条件路由逻辑 — 统一管理所有 Agent 的条件判断


每个 should_continue_xxx 方法:
  1. 检查 tool_call_count 防止死循环
  2. 检查是否已有产出（sql_result / chart_json / draft_report）
  3. 检查上一条消息是否有 tool_calls
  4. 返回下一个节点名称字符串
"""

import logging

from backend.agent.utils.state import DataAnalysisState

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """条件路由——每个 Agent 执行完后决定下一步去哪"""

    def __init__(
        self,
        max_sql_retries: int = 2,
        max_debate_rounds: int = 2,
    ):
        self.max_sql_retries = max_sql_retries
        self.max_debate_rounds = max_debate_rounds

    # ═══════════════════════════════════════════════════════════
    # SQL Agent 路由
    # ═══════════════════════════════════════════════════════════

    def should_continue_sql(self, state: DataAnalysisState) -> str:
        """
        SQL Agent → tools_sql / retry / Msg Clear SQL / Chart Agent / Report Agent

        优先级:
          1. 有 tool_calls → tools_sql (执行SQL)
          2. 有 sql_error + 未超重试 → SQL Agent (重试)
          3. SQL 完成，下一步是 chart → 跳过 Msg Clear/Step Advance，直接到 Chart Agent
          4. SQL 完成，下一步是 finalize 或没有更多步骤 → 跳过 Msg Clear/Step Advance，直接到 Report Agent
          5. 否则 → Msg Clear SQL → Step Advance SQL → 继续
        """
        messages = state.get("messages", [])
        if not messages:
            return "Msg Clear SQL"

        last_msg = messages[-1]
        tool_call_count = state.get("sql_retry_count", 0)
        sql_error = state.get("sql_error", "")

        has_tool_calls = bool(hasattr(last_msg, "tool_calls") and last_msg.tool_calls)

        logger.info(
            "[条件路由] SQL — tool_calls=%s retry=%d error=%s",
            has_tool_calls, tool_call_count, bool(sql_error),
        )

        # 还有工具调用需要执行
        if has_tool_calls:
            if tool_call_count >= self.max_sql_retries + 1:
                logger.warning("[死循环防护] 强制结束 → Msg Clear SQL")
                return "Msg Clear SQL"
            return "tools_sql"

        # 有错误且未超重试次数 → 重试
        if sql_error and tool_call_count < self.max_sql_retries:
            return "SQL Agent"

        # SQL 已完成，根据计划直接路由到下一步（跳过 Msg Clear + Step Advance）
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)

        # 注意: SQL Agent 节点内部可能已经将 current_step_index 推进到下一步，
        # 所以直接用 current_step 作为"当前应该执行的步骤索引"，无需 +1
        if current_step < len(plan):
            current_type = plan[current_step].get("type", "sql")
            if current_type == "chart":
                logger.info("[条件路由] SQL 完成 → 直接到 Chart Agent (step %d)", current_step + 1)
                return "Chart Agent"
            elif current_type == "finalize":
                logger.info("[条件路由] SQL 完成 → 直接到 Report Agent (step %d 为 finalize)", current_step + 1)
                return "Report Agent"
            elif current_type == "sql":
                logger.info("[条件路由] SQL 完成 → 继续 SQL Agent (step %d)", current_step + 1)
                return "SQL Agent"

        return "Msg Clear SQL"

    # ═══════════════════════════════════════════════════════════
    # Chart Agent 路由
    # ═══════════════════════════════════════════════════════════

    def should_continue_chart(self, state: DataAnalysisState) -> str:
        """Chart Agent → tools_chart / Msg Clear Chart / Report Agent / SQL Agent"""
        messages = state.get("messages", [])
        if not messages:
            return "Msg Clear Chart"
        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools_chart"

        # Chart 完成，根据计划直接路由到下一步
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)
        next_idx = current_step + 1

        if next_idx < len(plan):
            next_type = plan[next_idx].get("type", "sql")
            if next_type == "sql":
                logger.info("[条件路由] Chart 完成 → 直接到 SQL Agent (step %d)", next_idx + 1)
                return "SQL Agent"
            elif next_type == "finalize":
                logger.info("[条件路由] Chart 完成 → 直接到 Report Agent (step %d 为 finalize)", next_idx + 1)
                return "Report Agent"

        return "Msg Clear Chart"

    # ═══════════════════════════════════════════════════════════
    # 辩论路由
    # ═══════════════════════════════════════════════════════════

    def should_continue_debate(self, state: DataAnalysisState) -> str:
        """
        辩论循环路由 —— Optimistic ↔ Pessimistic 交替发言

        """
        debate_state = state.get("debate_state", {})
        latest_speaker = debate_state.get("latest_speaker", "")
        round_count = debate_state.get("round_count", 0)

        logger.info(
            "[辩论路由] 轮次=%d/%d 发言人=%s", round_count, self.max_debate_rounds, latest_speaker
        )

        # max_debate_rounds 轮 = 双方各发言 max_debate_rounds 次
        max_speeches = self.max_debate_rounds * 2

        if round_count >= max_speeches:
            logger.info("[辩论路由] 结束 → Validator (%d/%d 次发言)", round_count, max_speeches)
            return "Validator"

        # 交替发言
        if latest_speaker == "optimistic":
            return "Pessimistic"
        else:
            return "Optimistic"

    # ═══════════════════════════════════════════════════════════
    # Report Agent 路由
    # ═══════════════════════════════════════════════════════════

    def should_continue_after_report(self, state: DataAnalysisState) -> str:
        """
        Report Agent → Optimistic (首次进入辩论) / Validator (修订后直接验证)

        避免修订后再次进入辩论循环造成死循环。
        """
        revision_count = state.get("revision_count", 0)

        if revision_count > 0:
            logger.info("[条件路由] Report (修订%d) → Validator (跳过辩论)", revision_count)
            return "Validator"

        logger.info("[条件路由] Report (首次) → Optimistic (进入辩论)")
        return "Optimistic"

    # ═══════════════════════════════════════════════════════════
    # Validator 路由
    # ═══════════════════════════════════════════════════════════

    def should_continue_after_validator(self, state: DataAnalysisState) -> str:
        """
        Validator → END (通过/带建议通过) / Report Agent (驳回修正，最多 3 次) / END (需人工审核)

        v3.2 优化:
          - 新增 approved_with_suggestions: 通过但附优化建议，不触发修订循环
          - 最大修订次数从 2 提升到 3
        """
        result = state.get("validation_result", "approved")
        revision_count = state.get("revision_count", 0)

        if result in ("approved", "approved_with_suggestions"):
            tag = "✅" if result == "approved" else "💡"
            logger.info("[条件路由] Validator → END %s (%s)", tag, result)
            return "END"

        if result == "needs_review":
            logger.info("[条件路由] Validator → END (需人工审核)")
            return "END"

        MAX_REVISIONS = 3  # v3.2: 从 2 提升到 3
        if revision_count >= MAX_REVISIONS:
            logger.warning("[条件路由] 修订已达上限(%d)，强制结束", revision_count)
            return "END"

        logger.info("[条件路由] Validator → Report Agent (第%d次修订)", revision_count + 1)
        return "Report Agent"

    # ═══════════════════════════════════════════════════════════
    # Planner → SQL Agent / Report Agent（v3.1: 显式终止步骤）
    # ═══════════════════════════════════════════════════════════

    def should_continue_after_planner(self, state: DataAnalysisState) -> str:
        """
        Planner → SQL Agent / Chart Agent / Report Agent（跳过后续）

        借鉴 data_analysis_agent 的显式 action 状态机:
          - 如果 Planner 输出包含 type=finalize 的步骤 → 直接跳到 Report Agent
          - 如果当前步骤是 chart → 跳到 Chart Agent
          - 否则 → SQL Agent

        这避免了依赖 LLM 自行判断何时终止的隐式行为。
        """
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)

        if not plan:
            logger.info("[条件路由] Planner → END (无计划)")
            return "END"

        # 查找是否有 finalize 步骤
        has_finalize = any(s.get("type") == "finalize" for s in plan)

        if current_step >= len(plan):
            if has_finalize:
                logger.info("[条件路由] Planner → Report Agent (finalize 触发)")
                return "Report Agent"
            logger.info("[条件路由] Planner → END (所有步骤完成)")
            return "END"

        current = plan[current_step]
        step_type = current.get("type", "sql")

        if step_type == "finalize":
            logger.info("[条件路由] Planner → Report Agent (当前步骤为 finalize)")
            return "Report Agent"
        elif step_type == "chart":
            logger.info("[条件路由] Planner → Chart Agent")
            return "Chart Agent"
        else:
            logger.info("[条件路由] Planner → SQL Agent (step %d/%d)", current_step + 1, len(plan))
            return "SQL Agent"

    # ═══════════════════════════════════════════════════════════
    # SQL/Chart Agent → 下一步路由（v3.1: 支持 finalize 步骤跳过）
    # ═══════════════════════════════════════════════════════════

    def should_continue_after_sql(self, state: DataAnalysisState) -> str:
        """
        Msg Clear SQL → Chart Agent / Report Agent / SQL Agent

        检查当前步骤（Step Advance 已将其指向下一步）的类型:
          - chart → Chart Agent
          - sql → SQL Agent（继续执行）
          - finalize → Report Agent
          - 无更多步骤 → Report Agent (兜底)

        注意: current_step_index 已被 Step Advance 推进到下一步，
        所以这里直接用 current_step 检查，无需再 +1。
        """
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)

        if current_step < len(plan):
            current_type = plan[current_step].get("type", "sql")
            logger.info("[条件路由] Step Advance SQL: current_step=%d, plan_len=%d, types=%s",
                        current_step, len(plan),
                        [s.get("type") for s in plan])
            if current_type == "chart":
                logger.info("[条件路由] Step Advance SQL → Chart Agent (step %d)", current_step + 1)
                return "Chart Agent"
            elif current_type == "sql":
                logger.info("[条件路由] Step Advance SQL → SQL Agent (step %d)", current_step + 1)
                return "SQL Agent"
            elif current_type == "finalize":
                logger.info("[条件路由] Step Advance SQL → Report Agent (step %d 为 finalize)", current_step + 1)
                return "Report Agent"

        logger.info("[条件路由] Step Advance SQL → Report Agent (兜底)")
        return "Report Agent"

    def should_continue_after_chart(self, state: DataAnalysisState) -> str:
        """
        Msg Clear Chart → SQL Agent (还有SQL步骤) / Report Agent

        检查是否还有未执行的步骤:
          - 下一步为 sql → SQL Agent
          - 下一步为 finalize / 无更多步骤 → Report Agent

        注意: current_step_index 已被 Step Advance 推进到下一步。
        """
        plan = state.get("plan", [])
        current_step = state.get("current_step_index", 0)

        if current_step < len(plan):
            current_type = plan[current_step].get("type", "sql")
            if current_type == "sql":
                logger.info("[条件路由] Step Advance Chart → SQL Agent (step %d)", current_step + 1)
                return "SQL Agent"
            elif current_type == "finalize":
                logger.info("[条件路由] Step Advance Chart → Report Agent (step %d 为 finalize)", current_step + 1)
                return "Report Agent"

        logger.info("[条件路由] Step Advance Chart → Report Agent (兜底)")
        return "Report Agent"
