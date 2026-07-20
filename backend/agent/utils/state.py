"""
Agent 状态定义

LangGraph 使用 TypedDict 定义全局状态，每个 Agent 节点读取和写入 state 字段。

设计原则:
  - 继承 MessagesState: 保证 messages 字段兼容 LangGraph 内置 ToolNode
  - 每个 Agent 有独立的产出字段: 方便下游读取，也方便 SSE 推送给前端展示
  - 计数器防无限循环: sql_retry_count / debate_round_count / revision_count
  - 工作记忆: Agent 间结构化的共享上下文（v2.0 新增）
  - ReAct 追踪: 记录每个 Agent 的推理步骤（v2.0 新增）
"""

from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


class DebateState(TypedDict):
    """辩论子状态 — 类似原项目的 InvestDebateState"""

    optimistic_history: Annotated[str, "正方发言历史"]
    pessimistic_history: Annotated[str, "反方发言历史"]
    latest_speaker: Annotated[str, "最近发言方: optimistic / pessimistic"]
    round_count: Annotated[int, "当前辩论轮次"]


class WorkingMemory(TypedDict, total=False):
    """
    Agent 间共享的结构化工作记忆

    每个 Agent 在执行过程中向其中添加发现和观察结果，
    下游 Agent 读取这些信息以避免重复工作。
    """

    findings: Annotated[list[dict], "关键发现: [{agent, finding, confidence}]"]
    observations: Annotated[list[str], "执行过程中的观察"]
    decisions: Annotated[list[dict], "Agent 做出的决策: [{agent, decision, reason}]"]
    open_questions: Annotated[list[str], "尚未解决的问题"]


class SharedEvidence(TypedDict, total=False):
    """辩论双方共享的证据空间"""

    data_points: Annotated[list[dict], "双方引用过的数据点 [{value, source, cited_by}]"]
    agreed_facts: Annotated[list[str], "双方共识"]
    disputed_claims: Annotated[list[dict], "争议焦点 [{claim, optimistic_view, pessimistic_view}]"]


class DebateScore(TypedDict, total=False):
    """辩论评分"""

    optimistic_score: Annotated[float, "正方总分 (0-100)"]
    pessimistic_score: Annotated[float, "反方总分 (0-100)"]
    optimistic_breakdown: Annotated[dict, "正方分项: {argument_quality, data_support, rebuttal}"]
    pessimistic_breakdown: Annotated[dict, "反方分项"]
    winner: Annotated[str, "辩论胜方: optimistic / pessimistic / tie"]
    summary: Annotated[str, "评分理由"]


class DataAnalysisState(MessagesState):
    """
    Multi-Agent 数据分析全局状态

    生命周期贯穿整个分析流程:
      Planner → SQL Agent → Chart Agent → Report Agent
      → Optimistic ↔ Pessimistic (辩论) → Validator → END
    """

    # ─── 用户输入 ───
    user_query: Annotated[str, "用户提出的数据分析问题"]

    # ─── 数据源信息（启动时由 API 层注入） ───
    available_tables: Annotated[list[str], "当前可查询的表名列表"]
    table_schemas_text: Annotated[str, "所有表结构的文本描述（注入 Agent prompt）"]

    # ─── Planner 产出 ───
    plan: Annotated[list[dict], "执行计划: [{'step': 1, 'task': '...', 'type': 'sql', 'depends_on': []}, ...]"]
    current_step_index: Annotated[int, "当前正在执行的步骤索引"]

    # ─── SQL Agent 产出 ───
    sql_query: Annotated[str, "最近一次执行的 SQL 语句"]
    sql_result: Annotated[str, "SQL 查询结果（CSV 格式文本）"]
    sql_error: Annotated[str, "SQL 错误信息（成功执行时为空）"]
    sql_retry_count: Annotated[int, "SQL 重试次数，超过 2 次停止重试"]

    # ─── Chart Agent 产出 ───
    chart_json: Annotated[dict | None, "Plotly Figure JSON（已废弃，保留兼容）"]
    chart_files: Annotated[list[str], "生成的 PNG 图表文件路径列表"]
    chart_config: Annotated[dict, "图表配置: {title, chart_type, x_axis, y_axis}"]

    # ─── Report Agent 产出 ───
    draft_report: Annotated[str, "报告草稿（辩论前）"]

    # ─── 辩论阶段 ───
    debate_state: Annotated[DebateState, "辩论子状态（含轮次计数）"]
    optimistic_view: Annotated[str, "正方（乐观）观点"]
    pessimistic_view: Annotated[str, "反方（悲观）观点"]
    shared_evidence: Annotated[SharedEvidence, "辩论双方共享的证据空间"]
    debate_scores: Annotated[DebateScore | None, "辩论评分结果"]

    # ─── Validator 产出 ───
    validation_result: Annotated[str, "裁判结果: 'approved' / 'rejected' / 'needs_review'"]
    validation_reason: Annotated[str, "裁判理由"]
    revision_count: Annotated[int, "报告修订次数（防无限循环，最多2次）"]

    # ─── 最终输出 ───
    final_report: Annotated[str, "最终分析报告（Markdown 格式）"]

    # ─── 流式进度（SSE 推给前端） ───
    progress_message: Annotated[str, "当前进度描述，实时推送给前端展示"]

    # ─── 工作记忆（v2.0 — Agent 间共享上下文） ───
    working_memory: Annotated[WorkingMemory, "Agent 间共享的结构化发现和观察"]
    agent_reflections: Annotated[dict, "每个 Agent 的执行总结: {'SQL Agent': '...', ...}"]
    agent_memory_context: Annotated[dict[str, str], "每个 Agent 的历史记忆上下文（Per-Agent RAG）"]

    # ─── ReAct 追踪（v2.0 — 记录推理步骤） ───
    react_intermediate_steps: Annotated[list[dict], "最近一个 Agent 的 ReAct 推理步骤"]
    react_iterations: Annotated[int, "最近一个 Agent 的 ReAct 迭代次数"]

    # ─── 评估（v2.0 — Agent 输出质量评分） ───
    evaluation: Annotated[dict | None, "Agent 评估结果: {overall_score, evaluations, warnings}"]

    # ─── 性能指标（propagate() 自动填充） ───
    performance_metrics: Annotated[dict | None, "节点性能统计"]


# 初始状态由 backend.graph.propagation.Propagator.create_initial_state() 创建
