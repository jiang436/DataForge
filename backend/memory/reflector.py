"""
分析反思器 — 仿 TradingAgents-CN 的 Per-Agent 反思存储

参考: tradingagents/graph/trading_graph.py → reflect_and_remember()

v3.0 变更（Per-Agent RAG）:
  原: 反思完成后存入全局 "analysis_history" collection
  新: 每个 Agent 的经验分别存入各自的 collection
      - Planner: 存储计划质量反馈
      - SQL Agent: 存储查询策略和错误恢复经验
      - Report Agent: 存储报告撰写策略
      - Validator: 存储验证教训
"""

import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.memory.memory_store import get_agent_memory
from backend.utils.json_parser import parse_llm_json

logger = logging.getLogger("memory")

REFLECTION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        '你是数据分析反思专家。\n\n'
        '## 任务\n'
        '回顾本次分析，为每个参与的 Agent 提取经验教训。\n\n'
        '## 输出格式\n'
        '请输出 JSON（不要输出其他内容）:\n\n'
        '{{"planner": {{"situation": "...", "advice": "...", "outcome": "..."}},\n'
        ' "sql_agent": {{"situation": "...", "advice": "...", "outcome": "..."}},\n'
        ' "report_agent": {{"situation": "...", "advice": "...", "outcome": "..."}},\n'
        ' "validator": {{"situation": "...", "advice": "...", "outcome": "..."}},\n'
        ' "lessons": ["经验1"],\n'
        ' "summary": "一句话总结"}}',
    ),
    (
        "human",
        "## 用户原始问题\n{user_query}\n\n"
        "## 分析报告\n{draft_report}\n\n"
        "## SQL 查询\n{sql_query}\n\n"
        "## SQL 结果（前 500 字符）\n{sql_result}\n\n"
        "## Validator 裁判\n{validation_result}: {validation_reason}\n\n"
        "请为每个 Agent 提取经验教训。",
    ),
])


class Reflector:
    """
    分析反思器 — 仿 TradingAgents-CN 的反思模式

    用法:
        reflector = Reflector(llm)
        reflector.reflect_and_remember(state)
    """

    def __init__(self, llm: ChatOpenAI):
        self.llm = llm
        self.chain = REFLECTION_PROMPT | llm

    def reflect_and_remember(self, state: dict) -> dict:
        """
        反思本次分析，为每个 Agent 分别存入经验

        Args:
            state: 最终分析状态（DataAnalysisState）

        Returns:
            {"planner": {...}, "sql_agent": {...}, ...}
        """
        user_query = state.get("user_query", "")
        draft_report = state.get("final_report", "") or state.get("draft_report", "")

        if not draft_report or len(draft_report) < 50:
            logger.info("报告内容过短，跳过反思")
            return {}

        logger.info("开始反思本次分析（Per-Agent 模式）...")

        try:
            response = self.chain.invoke({
                "user_query": user_query[:500],
                "draft_report": draft_report[:3000],
                "sql_query": state.get("sql_query", "")[:500],
                "sql_result": state.get("sql_result", "")[:500],
                "validation_result": state.get("validation_result", "approved"),
                "validation_reason": state.get("validation_reason", ""),
            })

            content = response.content if hasattr(response, "content") else str(response)
            parsed = self._parse_json(content)

            # ─── Per-Agent 存储 ───
            agent_names = ["planner", "sql_agent", "report_agent", "validator"]
            for agent_name in agent_names:
                agent_data = parsed.get(agent_name, {})
                if agent_data.get("situation"):
                    memory = get_agent_memory(agent_name)
                    memory.add_experience(
                        situation=agent_data.get("situation", ""),
                        advice=agent_data.get("advice", ""),
                        outcome=agent_data.get("outcome", ""),
                    )

            # 辩论双方共享经验（存入各自记忆库）
            for debate_side in ["optimistic", "pessimistic"]:
                debate_data = parsed.get(debate_side)
                if debate_data and debate_data.get("situation"):
                    memory = get_agent_memory(debate_side)
                    memory.add_experience(
                        situation=debate_data.get("situation", ""),
                        advice=debate_data.get("advice", ""),
                        outcome=debate_data.get("outcome", ""),
                    )

            lessons = parsed.get("lessons", [])
            logger.info(
                "反思完成 (Per-Agent): %d 个 Agent 经验已存储, %d 条全局经验",
                sum(1 for a in agent_names if parsed.get(a, {}).get("situation")),
                len(lessons),
            )

            return parsed
        except Exception as e:
            logger.warning("反思失败（非致命）: %s", e)
            return {}

    def _parse_json(self, content: str) -> dict:
        """解析 LLM 输出的 JSON（使用共享解析器）"""
        return parse_llm_json(content, description="反思器输出")


def get_historical_context(agent_name: str, user_query: str, n: int = 2) -> str:
    """
    检索指定 Agent 的历史经验上下文（Per-Agent 版本）

    Args:
        agent_name:  Agent 名称（如 "planner", "sql_agent"）
        user_query: 当前用户问题
        n:          检索条数

    Returns:
        格式化的历史上下文文本
    """
    memory = get_agent_memory(agent_name)
    return memory.format_context(user_query, n=n)
