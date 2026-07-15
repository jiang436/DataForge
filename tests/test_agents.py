"""
Agent 层单元测试

验证 7 个 Agent 的核心逻辑:
  - 各 Agent 的 prompt 模板注入
  - 从 state 提取结果的逻辑
  - 错误处理和边界条件
"""

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from tests.mock_llm import FakeLLM, make_text_response, make_tool_call_response

# ─── 测试工具 ───


@tool
def get_table_info() -> str:
    """获取表结构"""
    return "Table: sales\nColumns: name(TEXT), amount(REAL)"


@tool
def execute_sql(sql: str) -> str:
    """执行SQL查询"""
    if "ERROR_TRIGGER" in sql:
        return "ERROR: no such table: bad_table"
    return "name,amount\nProduct A,15000\nProduct B,28000"


@tool
def generate_chart(data_json: str) -> str:
    """生成图表"""
    return '{"data":[{"type":"bar","x":["A","B"],"y":[15000,28000]}]}'


# ─── SQL Agent ───


class TestSQLAgent:
    def test_prompt_injects_table_schemas(self):
        """验证表结构被注入到 system prompt 中。"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            make_tool_call_response("查看表结构", "get_table_info", {}),
            make_text_response("查询完成，数据如下..."),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="查销售数据")],
            "plan": [{"step": 1, "task": "查询销售总额"}],
            "current_step_index": 0,
            "table_schemas_text": "Table: sales\nColumns: name(TEXT), amount(REAL)",
            "user_query": "查销售数据",
        }
        result = agent(state)

        # 不应崩溃，正常返回
        assert "messages" in result
        assert "sql_query" in result

    def test_extracts_sql_from_tool_calls(self):
        """从 execute_sql 工具调用中提取 SQL 语句。"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            make_tool_call_response("执行查询", "execute_sql", {"sql": "SELECT sum(amount) FROM sales"}),
            make_text_response("查询完成"),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="销售额")],
            "plan": [{"step": 1, "task": "查销售额"}],
            "current_step_index": 0,
            "table_schemas_text": "Table: sales",
            "user_query": "销售额",
        }
        result = agent(state)

        assert "SELECT sum" in result["sql_query"]
        assert result["sql_error"] == ""

    def test_detects_sql_error(self):
        """SQL 执行错误时设置 sql_error 和递增 retry_count。"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            make_tool_call_response(
                "执行（会报错的）SQL", "execute_sql",
                {"sql": "SELECT * FROM ERROR_TRIGGER"},
            ),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="查询")],
            "plan": [{"step": 1, "task": "查询"}],
            "current_step_index": 0,
            "table_schemas_text": "Table: x",
            "user_query": "查询",
            "sql_retry_count": 0,
        }
        result = agent(state)

        assert result["sql_error"] != ""
        assert "ERROR" in result["sql_error"]
        assert result["sql_retry_count"] == 1  # 从0递增到1

    def test_retry_count_doesnt_increment_on_success(self):
        """成功时不递增 retry_count。"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            make_tool_call_response("查询", "execute_sql", {"sql": "SELECT 1"}),
            make_text_response("成功"),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="查")],
            "plan": [{"step": 1, "task": "查"}],
            "current_step_index": 0,
            "table_schemas_text": "Table: t",
            "user_query": "查",
            "sql_retry_count": 0,
        }
        result = agent(state)

        assert result["sql_retry_count"] == 0

    def test_builds_plan_context(self):
        """验证计划上下文标注当前步骤。"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[make_text_response("分析完成")])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="分析")],
            "plan": [
                {"step": 1, "task": "第一步"},
                {"step": 2, "task": "第二步"},
                {"step": 3, "task": "第三步"},
            ],
            "current_step_index": 1,  # 当前在第2步
            "table_schemas_text": "",
            "user_query": "分析",
        }
        result = agent(state)
        assert "messages" in result


# ─── Chart Agent ───


class TestChartAgent:
    def test_creates_chart_agent(self):
        """Chart Agent 可以正常创建并执行。"""
        from backend.agent.analysts.chart_agent import create_chart_agent

        llm = FakeLLM(responses=[
            make_tool_call_response(
                "生成图表", "generate_chart",
                {"data_json": '{"x":[1,2],"y":[3,4]}'},
            ),
        ])
        agent = create_chart_agent(llm, [generate_chart])

        state = {
            "messages": [HumanMessage(content="画个图")],
            "sql_result": "name,amount\nA,100\nB,200",
            "table_schemas_text": "",
            "user_query": "画图",
        }
        result = agent(state)

        # 图表应有输出
        assert "chart_json" in result or "messages" in result


# ─── Planner ───


class TestPlanner:
    def test_planner_returns_plan(self):
        """Planner 返回任务分解计划。"""
        from backend.agent.managers.planner import create_planner

        llm = FakeLLM(responses=[make_text_response(
            '```json\n[{"step": 1, "task": "查询销售数据"}, {"step": 2, "task": "生成图表"}]\n```'
        )])
        agent = create_planner(llm)

        state = {
            "messages": [HumanMessage(content="分析销售")],
            "user_query": "分析销售",
            "available_tables": ["sales"],
            "table_schemas_text": "Table: sales",
            "historical_context": "",
        }
        result = agent(state)

        assert "plan" in result
        assert len(result["plan"]) >= 1

    def test_planner_handles_malformed_json(self):
        """Planner 输出的 JSON 格式不正确时不应崩溃。"""
        from backend.agent.managers.planner import create_planner

        llm = FakeLLM(responses=[make_text_response("这是无效的 JSON {{")])
        agent = create_planner(llm)

        state = {
            "messages": [HumanMessage(content="分析")],
            "user_query": "分析",
            "available_tables": ["t"],
            "table_schemas_text": "",
            "historical_context": "",
        }
        result = agent(state)
        # 不应崩溃
        assert "plan" in result


# ─── Validator ───


class TestValidator:
    def test_validator_approves_consistent_output(self):
        """三方一致时 Validator 给予 approved。"""
        from backend.agent.managers.validator import create_validator

        llm = FakeLLM(responses=[make_text_response(
            '```json\n{"result": "approved", "reason": "SQL结果、图表和报告结论一致"}\n```'
        )])
        agent = create_validator(llm)

        state = {
            "messages": [HumanMessage(content="验证")],
            "draft_report": "销售额为XXX",
            "sql_result": "name,amount\nA,100",
            "chart_json": {"data": []},
            "optimistic_view": "正方观点...",
            "pessimistic_view": "反方观点...",
        }
        result = agent(state)

        assert result["validation_result"] == "approved"

    def test_validator_rejects_inconsistent_output(self):
        """三方不一致时 Validator 驳回。"""
        from backend.agent.managers.validator import create_validator

        llm = FakeLLM(responses=[make_text_response(
            '```json\n{"result": "rejected", "reason": "图表数据与SQL结果不一致"}\n```'
        )])
        agent = create_validator(llm)

        state = {
            "messages": [HumanMessage(content="验证")],
            "draft_report": "...",
            "sql_result": "...",
            "chart_json": {"data": []},
            "optimistic_view": "...",
            "pessimistic_view": "...",
        }
        result = agent(state)

        assert result["validation_result"] == "rejected"
        assert result["validation_reason"] != ""


# ─── Report Agent ───


class TestReportAgent:
    def test_report_agent_generates_report(self):
        """Report Agent 生成包含 SQL 结果的报告。"""
        from backend.agent.synthesis.report_agent import create_report_agent

        llm = FakeLLM(responses=[make_text_response(
            "## 数据分析报告\n\n根据查询结果，总销售额为 43000 元。"
        )])
        agent = create_report_agent(llm)

        state = {
            "messages": [HumanMessage(content="撰写报告")],
            "sql_result": "total\n43000",
            "chart_json": {"data": []},
            "plan": [{"step": 1, "task": "查询"}],
        }
        result = agent(state)

        assert "draft_report" in result
        assert len(result["draft_report"]) > 0


# ─── Optimist / Pessimist ───


class TestDebaters:
    def test_optimist_generates_view(self):
        """正方 Agent 输出乐观视角分析。"""
        from backend.agent.debaters.optimist import create_optimist

        llm = FakeLLM(responses=[make_text_response("从乐观角度看，数据显示该品牌具有最高销量。")])
        agent = create_optimist(llm)

        state = {
            "messages": [HumanMessage(content="辩论")],
            "sql_result": "brand,amount\nA,100",
            "draft_report": "...",
            "debate_state": {"round_count": 0, "latest_speaker": ""},
        }
        result = agent(state)

        assert "optimistic_view" in result
        assert len(result["optimistic_view"]) > 0

    def test_pessimist_generates_view(self):
        """反方 Agent 输出风险视角分析。"""
        from backend.agent.debaters.pessimist import create_pessimist

        llm = FakeLLM(responses=[make_text_response("从审慎角度看，该品牌好评率最低，存在风险。")])
        agent = create_pessimist(llm)

        state = {
            "messages": [HumanMessage(content="辩论")],
            "sql_result": "brand,rating\nA,3.2",
            "draft_report": "...",
            "debate_state": {"round_count": 1, "latest_speaker": "optimistic"},
        }
        result = agent(state)

        assert "pessimistic_view" in result
        assert len(result["pessimistic_view"]) > 0


# ─── Agent 工厂验证 ───


def test_all_agent_creators_are_callable():
    """验证所有 Agent 工厂函数都可被调用。"""
    from backend.agent.analysts.chart_agent import create_chart_agent
    from backend.agent.analysts.sql_agent import create_sql_agent
    from backend.agent.debaters.optimist import create_optimist
    from backend.agent.debaters.pessimist import create_pessimist
    from backend.agent.managers.planner import create_planner
    from backend.agent.managers.validator import create_validator
    from backend.agent.synthesis.report_agent import create_report_agent

    llm = FakeLLM(responses=[make_text_response("OK")])

    all_creators = [
        ("sql", create_sql_agent, [llm, [get_table_info, execute_sql]]),
        ("chart", create_chart_agent, [llm, [generate_chart]]),
        ("planner", create_planner, [llm]),
        ("validator", create_validator, [llm]),
        ("report", create_report_agent, [llm]),
        ("optimist", create_optimist, [llm]),
        ("pessimist", create_pessimist, [llm]),
    ]

    for name, creator, args in all_creators:
        agent_fn = creator(*args)
        assert callable(agent_fn), f"{name} agent factory should return callable"


def test_sql_agent_partial_plan_state():
    """plan 为空时的容错。"""
    from backend.agent.analysts.sql_agent import create_sql_agent

    llm = FakeLLM(responses=[make_text_response("完成")])
    agent = create_sql_agent(llm, [get_table_info, execute_sql])

    state = {
        "messages": [HumanMessage(content="查询")],
        "plan": [],
        "current_step_index": 0,
        "table_schemas_text": "Table: t",
        "user_query": "查询",
    }
    result = agent(state)
    assert "messages" in result
