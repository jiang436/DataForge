"""Agent prompt 行为测试

测试关键 prompt 模板的结构和约束，不依赖真实 LLM 调用。
"""


from unittest.mock import MagicMock

import pytest

from backend.agent.analysts.chart_agent import CHART_AGENT_SYSTEM_PROMPT, create_chart_agent
from backend.agent.analysts.sql_agent import SQL_AGENT_SYSTEM_PROMPT, create_sql_agent
from backend.agent.debaters.optimist import OPTIMIST_SYSTEM_PROMPT, create_optimist
from backend.agent.debaters.pessimist import PESSIMIST_SYSTEM_PROMPT, create_pessimist
from backend.agent.managers.planner import PLANNER_SYSTEM_PROMPT, create_planner
from backend.agent.managers.validator import (
    VALIDATOR_SYSTEM_PROMPT,
    _parse_validator_output,
    _validate_result,
    create_validator,
)
from backend.agent.synthesis.report_agent import REPORT_SYSTEM_PROMPT, create_report_agent
from backend.agent.utils.react import create_react_agent

# ═══════════════════════════════════════════════════════════
# Prompt 模板结构测试
# ═══════════════════════════════════════════════════════════


class TestPlannerPrompt:
    def test_contains_required_sections(self):
        assert "任务规划" in PLANNER_SYSTEM_PROMPT or "拆解" in PLANNER_SYSTEM_PROMPT
        assert "可用数据表" in PLANNER_SYSTEM_PROMPT
        assert "输出格式" in PLANNER_SYSTEM_PROMPT
        assert "JSON" in PLANNER_SYSTEM_PROMPT

    def test_contains_step_types(self):
        assert "sql" in PLANNER_SYSTEM_PROMPT.lower()
        assert "chart" in PLANNER_SYSTEM_PROMPT.lower()

    def test_requires_json_output(self):
        assert "json" in PLANNER_SYSTEM_PROMPT.lower()
        assert "plan" in PLANNER_SYSTEM_PROMPT

    def test_max_steps_limit(self):
        assert "5" in PLANNER_SYSTEM_PROMPT  # "不要超过5步"

    def test_depends_on_field(self):
        assert "depends_on" in PLANNER_SYSTEM_PROMPT


class TestSQLAgentPrompt:
    def test_contains_table_schemas_placeholder(self):
        assert "{table_schemas}" in SQL_AGENT_SYSTEM_PROMPT

    def test_contains_task_placeholder(self):
        assert "{current_task}" in SQL_AGENT_SYSTEM_PROMPT

    def test_mentions_select_only(self):
        assert "SELECT" in SQL_AGENT_SYSTEM_PROMPT

    def test_contains_retry_instructions(self):
        prompt_lower = SQL_AGENT_SYSTEM_PROMPT.lower()
        assert "重试" in prompt_lower or "retry" in prompt_lower

    def test_mentions_get_table_info(self):
        assert "get_table_info" in SQL_AGENT_SYSTEM_PROMPT.lower()

    def test_mentions_execute_sql(self):
        assert "execute_sql" in SQL_AGENT_SYSTEM_PROMPT.lower()


class TestChartAgentPrompt:
    def test_contains_chart_types(self):
        assert "line" in CHART_AGENT_SYSTEM_PROMPT.lower()
        assert "bar" in CHART_AGENT_SYSTEM_PROMPT.lower()

    def test_contains_data_json_format(self):
        # v3.2: 新 prompt 使用 execute_python_code 的 matplotlib 代码格式
        # data_json 不再是主要路径，改为检查代码执行相关内容
        assert "execute_python_code" in CHART_AGENT_SYSTEM_PROMPT or \
               "data_json" in CHART_AGENT_SYSTEM_PROMPT

    def test_anti_hallucination_rule(self):
        assert "绝对禁止编造数据" in CHART_AGENT_SYSTEM_PROMPT

    def test_empty_data_handling(self):
        prompt = CHART_AGENT_SYSTEM_PROMPT.lower()
        assert "不适合可视化" in prompt or "不" in prompt


class TestReportAgentPrompt:
    def test_anti_hallucination_rule(self):
        assert "绝对禁止编造数据" in REPORT_SYSTEM_PROMPT

    def test_only_use_sql_results(self):
        assert "唯一的数据来源" in REPORT_SYSTEM_PROMPT

    def test_contains_user_query_placeholder(self):
        assert "{user_query}" in REPORT_SYSTEM_PROMPT

    def test_contains_sql_results_placeholder(self):
        assert "{sql_results}" in REPORT_SYSTEM_PROMPT

    def test_data_insufficient_handling(self):
        assert "数据不足" in REPORT_SYSTEM_PROMPT


class TestDebatePrompts:
    def test_optimist_has_positive_stance(self):
        assert "乐观" in OPTIMIST_SYSTEM_PROMPT

    def test_pessimist_has_risk_stance(self):
        assert "风险" in PESSIMIST_SYSTEM_PROMPT or "谨慎" in PESSIMIST_SYSTEM_PROMPT

    def test_both_have_round_prompts(self):
        # 双方都应该有第一轮提示（v3.0：第二轮改为动态构建）
        from backend.agent.debaters.optimist import OPTIMIST_FIRST_ROUND_PROMPT
        from backend.agent.debaters.pessimist import PESSIMIST_FIRST_ROUND_PROMPT

        assert "第一轮" in OPTIMIST_FIRST_ROUND_PROMPT or "first" in OPTIMIST_FIRST_ROUND_PROMPT.lower()
        assert "第一轮" in PESSIMIST_FIRST_ROUND_PROMPT or "first" in PESSIMIST_FIRST_ROUND_PROMPT.lower()

        # 验证第二轮上下文是动态构建的（通过 create_xxx 函数）
        from backend.agent.debaters.optimist import create_optimist
        from backend.agent.debaters.pessimist import create_pessimist
        assert callable(create_optimist)
        assert callable(create_pessimist)

    def test_both_reference_opponent(self):
        # 第二轮应该引用对方观点
        assert "pessimistic_view" in OPTIMIST_SYSTEM_PROMPT.lower() or "悲观" in OPTIMIST_SYSTEM_PROMPT
        assert "optimistic_view" in PESSIMIST_SYSTEM_PROMPT.lower() or "乐观" in PESSIMIST_SYSTEM_PROMPT


class TestValidatorPrompt:
    def test_contains_validation_criteria(self):
        assert "数据一致性" in VALIDATOR_SYSTEM_PROMPT
        assert "逻辑一致性" in VALIDATOR_SYSTEM_PROMPT

    def test_requires_json_output(self):
        assert "JSON" in VALIDATOR_SYSTEM_PROMPT

    def test_has_strict_output_format(self):
        assert '"result"' in VALIDATOR_SYSTEM_PROMPT
        assert '"reason"' in VALIDATOR_SYSTEM_PROMPT

    def test_has_approved_and_rejected(self):
        assert "approved" in VALIDATOR_SYSTEM_PROMPT
        assert "rejected" in VALIDATOR_SYSTEM_PROMPT

    def test_result_only_two_values(self):
        assert "result 只能是" in VALIDATOR_SYSTEM_PROMPT.lower() or "不要输出其他值" in VALIDATOR_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# 输出解析测试
# ═══════════════════════════════════════════════════════════


class TestValidatorOutputParsing:
    def test_parse_valid_approved_json(self):
        content = '{"result": "approved", "reason": "报告优秀", "revise_suggestions": ""}'
        parsed = _parse_validator_output(content)
        assert parsed["result"] == "approved"

    def test_parse_valid_rejected_json(self):
        content = '{"result": "rejected", "reason": "数据有误", "revise_suggestions": "修正数据"}'
        parsed = _parse_validator_output(content)
        assert parsed["result"] == "rejected"

    def test_parse_json_in_markdown_block(self):
        content = '```json\n{"result": "approved", "reason": "ok", "revise_suggestions": ""}\n```'
        parsed = _parse_validator_output(content)
        assert parsed["result"] == "approved"

    def test_parse_invalid_raises(self):
        content = "这是一段没有 JSON 的普通文本"
        with pytest.raises(ValueError):
            _parse_validator_output(content)

    def test_validate_normalizes_unknown_result(self):
        parsed = {"result": "unknown_value", "reason": "test"}
        validated = _validate_result(parsed)
        assert validated["result"] == "needs_review"

    def test_validate_normalizes_reject_keywords(self):
        parsed = {"result": "驳回", "reason": "test"}
        validated = _validate_result(parsed)
        assert validated["result"] == "rejected"


# ═══════════════════════════════════════════════════════════
# Agent 工厂函数测试
# ═══════════════════════════════════════════════════════════


class TestAgentFactories:
    """测试 Agent 工厂函数返回的节点能正确执行并输出预期字段"""

    def _make_state(self, **overrides):
        """创建最小有效的 DataAnalysisState"""
        from langchain_core.messages import HumanMessage

        base = {
            "messages": [HumanMessage(content="测试查询")],
            "user_query": "哪个品牌销量最高？",
            "available_tables": ["test_sales"],
            "table_schemas_text": "Table: test_sales\nColumns: id(int), brand(text), sales(int)",
            "plan": [{"step": 1, "task": "查询销量排名", "type": "sql", "depends_on": []}],
            "current_step_index": 0,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
            "draft_report": "",
            "optimistic_view": "",
            "pessimistic_view": "",
            "debate_state": {"optimistic_history": "", "pessimistic_history": "",
                             "latest_speaker": "", "round_count": 0},
            "validation_result": "",
            "validation_reason": "",
            "revision_count": 0,
        }
        base.update(overrides)
        return base

    def test_planner_produces_plan(self):
        """Planner 节点应返回 plan 和 progress_message"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response(
            '```json\n{"plan": [{"step": 1, "task": "查询销量", "type": "sql", '
            '"expected_output": "排名", "depends_on": []}]}\n```'
        )])
        node = create_planner(llm)
        result = node(self._make_state())
        assert "plan" in result
        assert len(result["plan"]) >= 1
        assert result["plan"][0]["step"] == 1
        assert "progress_message" in result
        # 默认 current_step_index 从 0 开始
        assert result["current_step_index"] == 0

    def test_planner_handles_malformed_json(self):
        """Planner 输出格式错误时降级为默认单步计划，而非崩溃"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response("这不是 JSON {{")])
        node = create_planner(llm)
        result = node(self._make_state())
        assert len(result["plan"]) >= 1
        assert result["plan"][0]["type"] == "sql"

    def test_sql_agent_returns_expected_keys(self):
        """SQL Agent 节点应返回 sql_result / sql_error / progress_message"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response("查询完成，结果如下。")])
        tools = [MagicMock(), MagicMock(), MagicMock()]
        for i, name in enumerate(["get_table_info", "execute_sql", "validate_sql"]):
            tools[i].name = name

        node = create_sql_agent(llm, tools)
        result = node(self._make_state())
        assert "sql_result" in result
        assert "sql_error" in result
        assert "progress_message" in result
        assert "messages" in result

    def test_sql_agent_tracks_retry_count(self):
        """SQL Agent 出错时应递增 sql_retry_count"""
        from tests.mock_llm import FakeLLM

        # 强制 tool_call 触发 execute_sql → 观察错误结果
        llm = FakeLLM(responses=[{
            "content": "我来查询",
            "tool_calls": [{
                "name": "execute_sql",
                "args": {"sql": "SELECT * FROM bad_table"},
                "id": "call_1",
                "type": "tool_call",
            }],
        }])
        # 用 MagicMock 模拟工具返回错误
        bad_tool = MagicMock()
        bad_tool.name = "execute_sql"
        bad_tool.invoke.return_value = "ERROR: no such table: bad_table"
        info_tool = MagicMock()
        info_tool.name = "get_table_info"
        info_tool.invoke.return_value = "Table: test_sales"
        val_tool = MagicMock()
        val_tool.name = "validate_sql"
        val_tool.invoke.return_value = "INVALID"

        node = create_sql_agent(llm, [info_tool, bad_tool, val_tool])
        state = self._make_state()
        result = node(state)
        # 工具返回 ERROR → sql_retry_count 递增
        assert result["sql_retry_count"] > 0

    def test_chart_agent_returns_progress(self):
        """Chart Agent 节点应返回 progress_message"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response("图表已生成。")])
        tools = [MagicMock()]
        tools[0].name = "generate_chart"
        node = create_chart_agent(llm, tools)
        result = node(self._make_state(sql_result="brand,sales\nA,100"))
        assert "progress_message" in result

    def test_report_agent_produces_draft(self):
        """Report Agent 应生成 draft_report"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response("## 分析结论\n戴尔销量最高。")])
        node = create_report_agent(llm)
        result = node(self._make_state(
            sql_result="brand,sales\nDell,80000",
            chart_json={"data": []},
        ))
        assert "draft_report" in result
        assert "progress_message" in result

    def test_optimist_produces_view(self):
        """Optimistic Agent 应生成 optimistic_view 并更新 debate_state"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response("### 乐观视角\n戴尔表现优秀，市场领先。")])
        node = create_optimist(llm)
        result = node(self._make_state(draft_report="戴尔销量最高"))
        assert "optimistic_view" in result
        assert result["debate_state"]["latest_speaker"] == "optimistic"
        assert result["debate_state"]["round_count"] >= 1

    def test_pessimist_produces_view(self):
        """Pessimistic Agent 应生成 pessimistic_view 并更新 debate_state"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response("### 风险视角\n需关注利润率下滑风险。")])
        node = create_pessimist(llm)
        result = node(self._make_state(draft_report="戴尔销量最高"))
        assert "pessimistic_view" in result
        assert result["debate_state"]["latest_speaker"] == "pessimistic"

    def test_validator_approves_good_report(self):
        """Validator 应对一致报告输出 approved"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response(
            '{"result": "approved", "reason": "数据一致", "revise_suggestions": ""}'
        )])
        node = create_validator(llm)
        result = node(self._make_state(
            draft_report="戴尔销量最高，80000件。",
            sql_result="brand,sales\nDell,80000",
            optimistic_view="戴尔表现优秀",
            pessimistic_view="需关注风险",
        ))
        assert result["validation_result"] == "approved"

    def test_validator_rejects_bad_report(self):
        """Validator 应对不一致报告输出 rejected"""
        from tests.mock_llm import FakeLLM, make_text_response

        llm = FakeLLM(responses=[make_text_response(
            '{"result": "rejected", "reason": "数据不一致", "revise_suggestions": "修正数值"}'
        )])
        node = create_validator(llm)
        result = node(self._make_state(
            draft_report="戴尔销量99999件",
            sql_result="brand,sales\nDell,80000",
        ))
        assert result["validation_result"] == "rejected"
        assert result["revision_count"] == 1


class TestReActFactory:
    """测试 ReAct 工厂函数"""

    def test_creates_callable(self):
        from unittest.mock import MagicMock
        llm = MagicMock()
        tools = [MagicMock(), MagicMock()]
        tool_names = ["tool_a", "tool_b"]
        for i, t in enumerate(tools):
            t.name = tool_names[i]

        node = create_react_agent(llm, tools, "test prompt")
        assert callable(node)

    def test_max_iterations_is_enforced(self):
        """ReAct 循环在达到 max_iterations 后停止，不会再调用工具"""
        from langchain_core.messages import HumanMessage

        from tests.mock_llm import FakeLLM

        # 让 LLM 每次都返回 tool_call（会触发无限循环），验证 max_iterations 生效
        responses = []
        for _ in range(6):
            responses.append({
                "content": "我需要查询",
                "tool_calls": [{
                    "name": "test_tool", "args": {}, "id": f"call_{_}",
                    "type": "tool_call",
                }],
            })
        llm = FakeLLM(responses=responses)
        tools = [MagicMock()]
        tools[0].name = "test_tool"
        tools[0].invoke.return_value = "tool result"

        node = create_react_agent(llm, tools, "test prompt", max_iterations=2)
        state = {"messages": [HumanMessage(content="查询")]}
        result = node(state)
        # 即使 LLM 始终返回 tool_call，ReAct 最多迭代 2 轮
        assert result["react_iterations"] <= 2

    def test_react_agent_stops_when_no_tool_call(self):
        """LLM 不返回 tool_call 时，ReAct 应在第一轮停止"""
        from langchain_core.messages import HumanMessage

        from tests.mock_llm import FakeLLM, make_text_response

        # FakeLLM 返回纯文本（无 tool_calls）
        llm = FakeLLM(responses=[make_text_response("分析完成，无需工具。")])
        tools = [MagicMock()]
        tools[0].name = "test_tool"
        tools[0].invoke.return_value = "ok"

        node = create_react_agent(llm, tools, "test", max_iterations=5)
        result = node({"messages": [HumanMessage(content="hi")]})
        # 第一轮就停止，没有 tool_call
        assert result["react_iterations"] == 1
        assert len(result["react_tool_calls"]) == 0


# ═══════════════════════════════════════════════════════════
# 集成测试（模拟 LLM）
# ═══════════════════════════════════════════════════════════


class TestSQLAgentNodeWithMockLLM:
    """用 Mock LLM 测试 SQL Agent 节点的行为"""

    def test_node_returns_expected_keys(self):
        from unittest.mock import MagicMock

        from langchain_core.messages import AIMessage, HumanMessage

        # 模拟 LLM 返回不含 tool_calls 的最终回答
        mock_response = AIMessage(content="查询完成，结果如上。")
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.stream.return_value = [mock_response]
        mock_llm.invoke.return_value = mock_response

        tools = [MagicMock(), MagicMock(), MagicMock()]
        for i, t in enumerate(tools):
            t.name = ["get_table_info", "execute_sql", "validate_sql"][i]

        node = create_sql_agent(mock_llm, tools)
        state = {
            "messages": [HumanMessage(content="测试")],
            "user_query": "测试查询",
            "plan": [{"step": 1, "task": "测试任务", "type": "sql"}],
            "current_step_index": 0,
            "table_schemas_text": "Table: test\nColumns: id(int)",
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = node(state)

        # 必须包含这些字段
        assert "sql_result" in result
        assert "sql_error" in result
        assert "progress_message" in result
        assert "messages" in result
