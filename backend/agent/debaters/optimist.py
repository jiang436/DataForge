"""
Optimistic Analyst — 正方辩论

负责:
  拿到报告草稿 → 从积极/乐观角度解读数据 → 提出支持增长的建议

角色类比: 原项目的 Bull Researcher（看多方）
LLM 策略: quick_think_llm，需要鲜明的"乐观"立场

v3.0 变更:
  - 注入完整辩论历史（不安限上一轮），强制逐条反驳对方论点
  - 共享证据追踪：自动提取引用数据点，标记 cited_by
  - 每轮明确要求回应对方引用的数据

辩论规则:
  - 第一轮: 独立阐述乐观视角的发现
  - 第二轮+: 逐条反驳 Pessimistic 观点，引用数据捍卫乐观立场
"""

import logging
import re

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.agent.utils.state import DataAnalysisState
from backend.prompts import load_prompt

logger = logging.getLogger(__name__)

OPTIMIST_SYSTEM_PROMPT = load_prompt("optimist")

OPTIMIST_FIRST_ROUND_PROMPT = (
    "这是第一轮辩论。请独立给出你的乐观分析，不要回应悲观方（悲观方还没有发言）。"
)


def _format_debate_history(debate_state: dict, my_side: str = "optimistic") -> str:
    """格式化完整辩论历史，供双方每轮参考"""
    opt_history = debate_state.get("optimistic_history", "")
    pess_history = debate_state.get("pessimistic_history", "")

    if not opt_history and not pess_history:
        return "(暂无辩论历史)"

    parts = ["## 完整辩论记录\n"]

    if opt_history:
        parts.append("### 正方（乐观方）发言历史")
        parts.append(opt_history if len(opt_history) < 3000 else opt_history[-3000:])

    if pess_history:
        parts.append("### 反方（谨慎方）发言历史")
        parts.append(pess_history if len(pess_history) < 3000 else pess_history[-3000:])

    # 共享证据
    shared = debate_state.get("shared_evidence", {})
    if shared.get("agreed_facts"):
        parts.append("### 双方共识")
        parts.extend(f"- {fact}" for fact in shared["agreed_facts"][-5:])
    if shared.get("disputed_claims"):
        parts.append("### 争议焦点")
        for claim in shared["disputed_claims"][-3:]:
            parts.append(f"- {claim.get('claim', '')}")

    return "\n".join(parts)


def _extract_data_points(text: str, cited_by: str) -> list[dict]:
    """从发言中提取数字/百分比，标记数据来源"""
    data_points = []
    # 百分比模式
    for m in re.finditer(r'(\d+[\.\d]*)\s*%', text):
        data_points.append({"value": f"{m.group(1)}%", "cited_by": cited_by})
    # 纯数字模式（只取≥100的显著数字，避免噪声）
    for m in re.finditer(r'(?<!\d)(\d{3,}(?:\.\d+)?)(?!\d)', text):
        val = m.group(1)
        if val not in {dp["value"] for dp in data_points}:
            data_points.append({"value": val, "cited_by": cited_by})
    return data_points[:8]


def create_optimist(llm):
    """
    创建 Optimistic Analyst 节点函数

    参考: tradingagents/agents/researchers/bull_researcher.py
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", OPTIMIST_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    chain = prompt | llm

    def optimist_node(state: DataAnalysisState) -> dict:
        """LangGraph 节点函数"""
        debate_state = state.get("debate_state", {})
        round_num = debate_state.get("round_count", 0) + 1
        logger.info("[Optimistic] 开始辩论 Round %d", round_num)

        draft_report = state.get("draft_report", "")
        pessimistic_view = state.get("pessimistic_view", "")
        sql_result = state.get("sql_result", "")

        # ─── 构建完整辩论上下文 ───
        full_history = _format_debate_history(debate_state, "optimistic")

        if round_num <= 1:
            debate_context = (
                "这是第一轮辩论。请独立给出你的乐观分析，不要回应悲观方。\n\n"
                + full_history
            )
        else:
            debate_context = (
                f"这是第 {round_num} 轮辩论。\n\n"
                f"对方（悲观方）上一轮的观点:\n{pessimistic_view[:2000]}\n\n"
                f"{full_history}\n\n"
                "## 本轮任务（必须逐条完成）:\n"
                "1. **逐一反驳**对方上一轮的核心论点，指出逻辑漏洞或数据误读\n"
                "2. **引用具体数据**强化自己的立场（优先使用 SQL 结果中的真实数字）\n"
                "3. 如果对方引用了你之前忽略的数据，**必须正面回应**\n"
                "4. 承认对方的合理观点（这展示你的客观性），但说明为什么整体上乐观视角更有说服力\n"
                f"5. 参考 SQL 结果: {sql_result[:500]}"
            )

        invoke_args = {
            "messages": state["messages"],
            "report": draft_report[:2000] if draft_report else "(暂无报告)",
            "draft_report": draft_report[:2000] if draft_report else "(暂无报告)",
            "debate_context": debate_context,
        }

        response = chain.invoke(invoke_args)

        view_content = response.content if hasattr(response, "content") else str(response)
        logger.info("[Optimistic] Round %d 完成，观点长度: %d", round_num, len(view_content))

        # ─── 更新辩论历史 ───
        debate_state = state.get("debate_state", {})
        prev_history = debate_state.get("optimistic_history", "")
        new_history = f"{prev_history}\n\n--- Round {round_num} (正方) ---\n{view_content}"

        # ─── 更新共享证据 ───
        shared_evidence = state.get("shared_evidence", {})
        # 提取数据点
        new_data_points = _extract_data_points(view_content, "optimistic")
        existing_points = shared_evidence.get("data_points", [])
        existing_values = {p.get("value", "") for p in existing_points}
        for dp in new_data_points:
            if dp["value"] not in existing_values:
                existing_points.append(dp)
                existing_values.add(dp["value"])
        shared_evidence["data_points"] = existing_points[-20:]

        return {
            "optimistic_view": view_content,
            "debate_state": {
                **debate_state,
                "optimistic_history": new_history,
                "latest_speaker": "optimistic",
                "round_count": round_num,
            },
            "shared_evidence": shared_evidence,
            "messages": [response],
            "progress_message": f"😊 正方辩论 Round {round_num}: 乐观视角分析完成",
        }

    return optimist_node
