"""
状态传播器 — 初始状态创建 + 图执行参数


v2.0 变更:
  - 新增 working_memory、agent_reflections 初始化
  - 新增 shared_evidence、debate_scores 初始化
  - 新增 evaluation、react_intermediate_steps 初始化
"""

from typing import Any

from langchain_core.messages import HumanMessage

from backend.agent.utils.state import DebateState, SharedEvidence, WorkingMemory


class Propagator:
    """图传播器 —— 创建初始状态、配置执行参数"""

    def __init__(self, max_recur_limit: int = 50):
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        user_query: str,
        available_tables: list[str],
        table_schemas_text: str,
        historical_context: str = "",
        agent_memory_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        创建 LangGraph 初始状态

        """

        # 将历史经验注入用户消息
        query_with_context = f"请分析以下数据问题：{user_query}\n"
        if historical_context:
            query_with_context += f"\n{historical_context}\n"

        query_with_context += f"\n可用数据表：\n{table_schemas_text}"

        return {
            "messages": [HumanMessage(content=query_with_context)],
            "user_query": user_query,
            "available_tables": available_tables,
            "table_schemas_text": table_schemas_text,
            # Planner 产出
            "plan": [],
            "current_step_index": 0,
            # SQL Agent 产出
            "sql_query": "",
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
            # Chart Agent 产出
            "chart_json": None,
            "chart_config": {},
            # Report Agent 产出
            "draft_report": "",
            # 辩论子状态
            "debate_state": DebateState(
                optimistic_history="",
                pessimistic_history="",
                latest_speaker="",
                round_count=0,
            ),
            "optimistic_view": "",
            "pessimistic_view": "",
            "shared_evidence": SharedEvidence(
                data_points=[],
                agreed_facts=[],
                disputed_claims=[],
            ),
            "debate_scores": None,
            # Validator 产出
            "validation_result": "",
            "validation_reason": "",
            "revision_count": 0,
            # 最终报告
            "final_report": "",
            # 进度消息
            "progress_message": "🚀 开始分析...",
            # 工作记忆（v2.0）
            "working_memory": WorkingMemory(
                findings=[],
                observations=[],
                decisions=[],
                open_questions=[],
            ),
            "agent_reflections": {},
            # ReAct 追踪（v2.0）
            "react_intermediate_steps": [],
            "react_iterations": 0,
            # 评估（v2.0）
            "evaluation": None,
            # Per-Agent RAG 上下文（v3.0）
            "agent_memory_context": agent_memory_context or {},
        }

    def get_graph_args(self, use_progress_callback: bool = False) -> dict[str, Any]:
        """
        获取 LangGraph 执行参数


        updates 模式: 每个节点完成后返回增量，用于进度回调
        values 模式:  返回完整状态，用于纯执行
        """
        stream_mode = "updates" if use_progress_callback else "values"
        return {
            "stream_mode": stream_mode,
            "config": {"recursion_limit": self.max_recur_limit},
        }

    # ─── 进度回调映射 ───
    PROGRESS_LABELS = {
        "Planner": "📋 任务规划中...",
        "SQL Agent": "🔍 查询数据中... (ReAct)",
        "tools_sql": "⚙️ 执行 SQL...",
        "Chart Agent": "📊 生成图表中... (ReAct)",
        "tools_chart": "⚙️ 渲染图表...",
        "Report Agent": "📝 撰写报告中...",
        "Optimistic": "😊 正方辩论中...",
        "Pessimistic": "😐 反方辩论中...",
        "Validator": "⚖️ 裁判验证中...",
    }

    def get_progress_label(self, node_name: str) -> str:
        """将节点名映射为中文进度标签"""
        return self.PROGRESS_LABELS.get(node_name, f"🔍 {node_name}")
