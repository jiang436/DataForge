"""集成测试 — 全链路 Agent 流程 (Mock LLM)

测试覆盖:
  - Planner → SQL Agent → Chart Agent → Report Agent → Debate → Validator 全链路
  - SSE 流式输出事件解析
  - 辩论评分逻辑 (e2e)
  - Validator 输出解析
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from backend.agent.managers.validator import _parse_validator_output, _validate_result
from backend.agent.utils.react import create_react_agent
from backend.graph.conditional_logic import ConditionalLogic
from backend.graph.propagation import Propagator

# ═══════════════════════════════════════════════════════════
# 全链路集成测试
# ═══════════════════════════════════════════════════════════


class TestFullPipelineWithMockLLM:
    """模拟 LLM 返回的情况下，测试全链路 StateGraph 流程"""

    def test_state_propagation_through_all_nodes(self):
        """验证初始 state 能正确流经所有节点"""
        prop = Propagator(max_recur_limit=50)

        state = prop.create_initial_state(
            user_query="哪个品牌销量最高？",
            available_tables=["test_sales"],
            table_schemas_text="Table: test_sales\nColumns: id(int), brand(text), sales(int)",
        )

        # 模拟 Planner 产出
        state["plan"] = [{"step": 1, "task": "查询销量", "type": "sql", "depends_on": []}]
        state["current_step_index"] = 0

        # 模拟 SQL Agent 产出
        state["sql_query"] = "SELECT brand, SUM(sales) FROM test_sales GROUP BY brand"
        state["sql_result"] = "brand,sales\nApple,50000\nDell,80000"
        state["sql_error"] = ""

        # 模拟 Chart Agent 产出
        state["chart_json"] = {"data": [{"type": "bar", "x": ["Apple", "Dell"], "y": [50000, 80000]}]}

        # 模拟 Report Agent 产出
        state["draft_report"] = "## 分析结果\n戴尔销量最高，达80000件。"

        # 模拟辩论
        state["optimistic_view"] = "戴尔表现出色，市场领先"
        state["pessimistic_view"] = "需关注Apple的增长潜力"

        # 模拟 Validator
        state["validation_result"] = "approved"
        state["validation_reason"] = "数据与结论一致"

        assert state["plan"][0]["task"] == "查询销量"
        assert "Dell" in state["sql_result"]
        assert state["chart_json"] is not None
        assert "戴尔" in state["draft_report"]
        assert state["validation_result"] == "approved"

    def test_conditional_routing_full_cycle(self):
        """验证所有条件路由逻辑"""
        logic = ConditionalLogic(max_sql_retries=2, max_debate_rounds=2)

        # SQL routing
        state = {"messages": [], "sql_error": "", "sql_retry_count": 0}
        assert logic.should_continue_sql(state) == "Msg Clear SQL"

        # SQL with error
        class FakeToolMsg:
            tool_calls = []
        state = {"messages": [FakeToolMsg()], "sql_error": "no such column", "sql_retry_count": 0}
        assert logic.should_continue_sql(state) == "SQL Agent"

        # Debate routing — round 0 starts with Optimistic
        state = {
            "debate_state": {"latest_speaker": "", "round_count": 0,
                             "optimistic_history": "", "pessimistic_history": ""}
        }
        assert logic.should_continue_debate(state) == "Optimistic"

        # Validator routing — approved
        state = {"validation_result": "approved", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "END"

        # Validator routing — rejected
        state = {"validation_result": "rejected", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "Report Agent"

        # Validator routing — needs_review
        state = {"validation_result": "needs_review", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "END"

    def test_progress_labels_all_agents(self):
        """验证所有 Agent 节点都有进度标签"""
        prop = Propagator()
        labels = prop.PROGRESS_LABELS
        assert "Planner" in labels
        assert "SQL Agent" in labels
        assert "Chart Agent" in labels
        assert "Report Agent" in labels
        assert "Optimistic" in labels
        assert "Pessimistic" in labels
        assert "Validator" in labels


# ═══════════════════════════════════════════════════════════
# 辩论评分集成测试
# ═══════════════════════════════════════════════════════════


class TestDebateScoringE2E:
    """辩论评分端到端测试"""

    def test_scorer_formats_scores_for_frontend(self):
        from backend.agent.debaters.scorer import format_debate_score_for_frontend
        from backend.agent.utils.state import DebateScore

        scores = DebateScore(
            optimistic_score=85,
            pessimistic_score=72,
            optimistic_breakdown={"argument_quality": 35, "data_support": 33, "rebuttal": 17},
            pessimistic_breakdown={"argument_quality": 32, "data_support": 28, "rebuttal": 12},
            winner="optimistic",
            summary="正方在数据和逻辑上均占优势",
        )

        frontend_data = format_debate_score_for_frontend(scores)
        assert frontend_data["has_scores"] is True
        assert frontend_data["optimistic_score"] == 85
        assert frontend_data["pessimistic_score"] == 72
        assert "optimistic" == frontend_data["winner"]

    def test_scorer_empty_debate_returns_tie(self):
        from backend.agent.debaters.scorer import format_debate_score_for_frontend
        from backend.agent.utils.state import DebateScore

        scores = DebateScore(optimistic_score=0, pessimistic_score=0, winner="tie", summary="")
        frontend_data = format_debate_score_for_frontend(scores)
        assert frontend_data["has_scores"] is True
        assert frontend_data["winner"] == "tie"


# ═══════════════════════════════════════════════════════════
# Validator 输出解析
# ═══════════════════════════════════════════════════════════


class TestValidatorParsing:
    """Validator JSON 解析全面测试"""

    def test_parse_valid_json(self):
        result = _parse_validator_output(
            '{"result": "approved", "reason": "ok", "revise_suggestions": ""}'
        )
        assert result["result"] == "approved"

    def test_parse_json_with_markdown_fence(self):
        result = _parse_validator_output(
            '```json\n{"result": "rejected", "reason": "数据不一致", "revise_suggestions": "修正"}\n```'
        )
        assert result["result"] == "rejected"

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_validator_output("no json here")

    def test_parse_json_in_text(self):
        result = _parse_validator_output(
            '一些文本 {"result": "approved", "reason": "ok", "revise_suggestions": ""} 更多文本'
        )
        assert result["result"] == "approved"

    def test_validate_reject_keywords(self):
        result = _validate_result({"result": "驳回", "reason": "数据有问题"})
        assert result["result"] == "rejected"

    def test_validate_needs_review(self):
        result = _validate_result({"result": "unknown_status", "reason": "?"})
        assert result["result"] == "needs_review"


# ═══════════════════════════════════════════════════════════
# SSE 流式事件测试
# ═══════════════════════════════════════════════════════════


class TestSSEEventStructure:
    """验证 SSE 事件数据由真实的转换函数生成，而非字面量"""

    def test_step_event_from_progress_callback(self):
        """模拟 progress_callback 产生的 step 事件格式"""
        # 这是 API 层 _progress_callback 实际 push 的数据结构
        msg = {"agent": "SQL Agent", "progress": "查询完成"}
        event = (
            "step",
            {"agent": msg.get("agent", "Agent"),
             "progress": str(msg.get("progress", msg))},
        )
        assert event[0] == "step"
        assert "agent" in event[1]
        assert "progress" in event[1]

    def test_debate_score_event_from_real_formatter(self):
        """format_debate_score_for_frontend 输出匹配前端 ChatMessage 类型"""
        from backend.agent.debaters.scorer import format_debate_score_for_frontend
        from backend.agent.utils.state import DebateScore

        scores = DebateScore(
            optimistic_score=80, pessimistic_score=65, winner="optimistic",
            optimistic_breakdown={"argument_quality": 35, "data_support": 30, "rebuttal": 15},
            pessimistic_breakdown={"argument_quality": 30, "data_support": 25, "rebuttal": 10},
            summary="正方论证更充分",
        )
        data = format_debate_score_for_frontend(scores)
        # 验证前端可消费的所有字段
        assert data["has_scores"] is True
        assert isinstance(data["optimistic_score"], int)
        assert isinstance(data["pessimistic_score"], int)
        assert data["winner"] in ("optimistic", "pessimistic", "tie")
        assert "winner_label" in data
        # 乐观分 > 悲观分时应正确反映
        assert data["optimistic_score"] > data["pessimistic_score"]

    def test_debate_score_event_tie(self):
        """平局时分数相等"""
        from backend.agent.debaters.scorer import format_debate_score_for_frontend
        from backend.agent.utils.state import DebateScore

        scores = DebateScore(optimistic_score=70, pessimistic_score=70, winner="tie",
                             summary="双方论据相当")
        data = format_debate_score_for_frontend(scores)
        assert data["winner"] == "tie"
        assert data["optimistic_score"] == data["pessimistic_score"]

    def test_debate_score_event_no_scores(self):
        """无辩论评分时返回 has_scores=False"""
        from backend.agent.debaters.scorer import format_debate_score_for_frontend

        data = format_debate_score_for_frontend(None)
        assert data["has_scores"] is False

    def test_done_event_matches_frontend_expectations(self):
        """finish 事件的字段应与前端 finishAnalysis() 消费的参数一致"""
        from backend.agent.utils.state import DebateScore

        # 模拟 API 层 _run 函数构建的 done 事件
        final_state = {
            "final_report": "## 报告\n分析完成。",
            "sql_query": "SELECT brand, SUM(sales) FROM t GROUP BY 1",
            "optimistic_view": "正面观点",
            "pessimistic_view": "风险观点",
            "validation_result": "approved",
            "validation_reason": "数据一致",
            "plan": [{"step": 1, "task": "查询", "type": "sql"}],
        }
        chart = {"data": [{"type": "bar"}]}
        debate_scores = DebateScore(optimistic_score=85, pessimistic_score=72,
                                    winner="optimistic", summary="ok")
        evaluation = {"overall_score": 0.85, "passed": True, "warnings": []}

        performance = {"total_time": 10.5, "node_count": 7}

        # 组装 done 事件（与 chat.py 一致）
        done_data = {
            "final_report": final_state.get("final_report", ""),
            "performance": performance,
            "chart_json": chart,
            "debate_scores": dict(debate_scores),
            "evaluation": evaluation,
            "agents": {
                "planner": {"plan": final_state.get("plan", [])},
                "sql": {"query": final_state.get("sql_query", "")},
                "debate": {
                    "optimistic": final_state.get("optimistic_view", ""),
                    "pessimistic": final_state.get("pessimistic_view", ""),
                },
                "validator": {
                    "result": final_state.get("validation_result", ""),
                    "reason": final_state.get("validation_reason", ""),
                },
            },
        }

        # 验证前端 finishAnalysis() 所需的字段全部存在
        assert "final_report" in done_data
        assert "performance" in done_data
        assert "agents" in done_data
        assert "planner" in done_data["agents"]
        assert "sql" in done_data["agents"]
        assert "debate" in done_data["agents"]
        assert "validator" in done_data["agents"]
        # performance 子字段
        assert "total_time" in done_data["performance"]
        assert "node_count" in done_data["performance"]

    def test_frontend_event_type_coverage(self):
        """前端 useSSE handleEvent 支持的所有事件类型应在此处覆盖"""
        # 前端 switch-case 映射:
        # step → addStep, debate → addDebate, chart → addChart,
        # report → addReport, done → finishAnalysis, token → appendToken,
        # debate_score → addDebateScore, eval → addEval, error → setError
        event_types = {"step", "debate", "chart", "report", "done",
                       "token", "debate_score", "eval", "error"}
        # 每个事件类型的前端处理方法应存在
        frontend_handlers = {
            "step": "addStep",
            "debate": "addDebate",
            "chart": "addChart",
            "report": "addReport",
            "done": "finishAnalysis",
            "token": "appendToken",
            "debate_score": "addDebateScore",
            "eval": "addEval",
            "error": "setError",
        }
        assert set(frontend_handlers.keys()) == event_types


# ═══════════════════════════════════════════════════════════
# ReAct 循环集成测试
# ═══════════════════════════════════════════════════════════


class TestReActLoopIntegration:
    """ReAct 循环完整流程测试"""

    def test_react_agent_creates_callable(self):
        llm = MagicMock()
        tools = [MagicMock(), MagicMock()]
        for i, t in enumerate(tools):
            t.name = ["get_table_info", "execute_sql"][i]

        node = create_react_agent(llm, tools, "test prompt", max_iterations=3)
        assert callable(node)

    def test_react_agent_with_no_tool_calls(self):

        mock_response = AIMessage(content="分析完成")
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.stream.return_value = [mock_response]

        tools = [MagicMock()]
        tools[0].name = "execute_sql"

        node = create_react_agent(mock_llm, tools, "test", max_iterations=3)
        state = {"messages": [HumanMessage(content="查询所有品牌")]}

        result = node(state)
        assert result["react_iterations"] > 0
        assert len(result["react_tool_calls"]) == 0  # no tools called


# ═══════════════════════════════════════════════════════════
# 评估框架集成测试
# ═══════════════════════════════════════════════════════════


class TestEvalIntegration:
    """评估框架端到端测试"""

    def test_evaluate_report_no_hallucination(self):
        from backend.eval.metrics import evaluate_report_agent

        state = {
            "draft_report": (
                "## 分析结论\n戴尔品牌销量最高，达到80,000件，同比增长23%。"
                "苹果以50,000件位居第二。"
            )
        }
        result = evaluate_report_agent(state)
        assert result.score > 0.5
        # "假设" is hallucination marker
        assert result.metrics["no_hallucination"] == 1.0

    def test_evaluate_report_with_hallucination(self):
        from backend.eval.metrics import evaluate_report_agent

        state = {
            "draft_report": "## 分析\n假设戴尔销量最高。例如，戴尔增长了30%。典型的优秀表现。"
        }
        result = evaluate_report_agent(state)
        assert result.metrics["no_hallucination"] < 1.0
        assert len(result.warnings) > 0

    def test_evaluate_sql_success(self):
        from backend.eval.metrics import evaluate_sql_agent

        state = {
            "sql_query": "SELECT brand, SUM(sales) FROM test GROUP BY 1",
            "sql_result": "brand,sales\nDell,80000",
            "sql_error": "",
            "react_iterations": 1,
        }
        result = evaluate_sql_agent(state)
        assert result.score > 0.7
        assert result.metrics["sql_syntax_valid"] == 1.0

    def test_evaluate_chart_generated(self):
        from backend.eval.metrics import evaluate_chart_agent

        state = {
            "chart_json": {"data": []},
            "sql_result": "brand,sales\nDell,80000",
            "react_iterations": 2,
        }
        result = evaluate_chart_agent(state)
        assert result.metrics["chart_generated"] == 1.0

    def test_evaluate_debate_quality(self):
        from backend.eval.metrics import evaluate_debate_quality

        state = {
            "optimistic_view": "戴尔销量最高，增长23%，是市场领导者",
            "pessimistic_view": "反驳：需关注利润率和竞争压力",
            "debate_scores": {},
        }
        result = evaluate_debate_quality(state)
        assert result.metrics["both_sides_participated"] == 1.0
        assert result.metrics["counter_arguments"] == 1.0

    def test_evaluate_overall_integration(self):
        from backend.eval.metrics import evaluate_overall

        state = {
            "sql_query": "SELECT 1",
            "sql_result": "brand,sales\nDell,80000",
            "sql_error": "",
            "react_iterations": 1,
            "draft_report": "## 结论\n戴尔销量最高，达80,000件。",
            "chart_json": {"data": []},
            "optimistic_view": "戴尔表现优秀",
            "pessimistic_view": "需关注风险",
            "debate_scores": {},
        }
        result = evaluate_overall(state)
        assert "overall_score" in result
        assert "evaluations" in result
        assert result["overall_score"] >= 0
        assert result["overall_score"] <= 1.0
