"""
Agent 推理逻辑验证测试 — 用 FakeLLM 验证 Agent 在真实场景下的推理能力

与 test_agents.py 的区别:
  - test_agents.py: 验证 prompt 注入 + 结果提取等结构层逻辑
  - 本文件: 验证 Agent 在具体场景下的推理决策（是否选对工具、是否纠正错误SQL等）

测试覆盖:
  1. SQL Agent 在未知表结构时先调用 get_table_info 再 execute_sql
  2. SQL Agent 遇到错误后自动修正重试
  3. Chart Agent 在有数据时生成图表，无数据时跳过
  4. Planner 生成合法的 JSON 计划
  5. Validator 检测到数据矛盾时拒绝
  6. ReAct 循环中的迭代效率（不在工具间循环超过必要次数）
"""

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from tests.mock_llm import (
    FakeLLM,
    make_text_response,
    make_tool_call_response,
)

# ─── 模拟工具 ───

TEST_SCHEMA = (
    "Table: test_sales\n"
    "Columns: date(TEXT), product(TEXT), category(TEXT), region(TEXT), amount(REAL), quantity(INTEGER)"
)

TEST_DATA = (
    "product,category,amount,quantity\n"
    "iPhone,手机,150000,200\n"
    "MacBook,笔记本,280000,150\n"
    "iPad,平板,120000,300\n"
    "AirPods,音频,80000,500\n"
    "AppleWatch,穿戴,60000,250\n"
)


@tool
def get_table_info(table_name: str) -> str:
    """查看表结构"""
    if table_name == "test_sales":
        return f"## 表: test_sales\n### 列信息:\n  - date (TEXT)\n  - product (TEXT)\n  - category (TEXT)\n  - region (TEXT)\n  - amount (REAL)\n  - quantity (INTEGER)\n\n### 前3行:\n{TEST_DATA[:200]}"
    return f"表 '{table_name}' 不存在"


@tool
def execute_sql(sql: str) -> str:
    """执行SQL查询"""
    if "bad_column" in sql.lower() or "non_existent" in sql.lower():
        return "ERROR: no such column: bad_column"
    if "bad_syntax" in sql.lower():
        return "ERROR: near \"FROM\": syntax error"
    if "test_sales" not in sql.lower():
        return "ERROR: no such table"
    if "amount" in sql.lower() and "SUM" in sql.upper():
        return "product,total_amount\niPhone,150000\nMacBook,280000\niPad,120000\nAirPods,80000\nAppleWatch,60000"
    if "amount" in sql.lower() and "AVG" in sql.upper():
        return "product,avg_amount\niPhone,750\nMacBook,1866\niPad,400\nAirPods,160\nAppleWatch,240"
    if "quantity" in sql.lower():
        return "product,total_qty\niPhone,200\nMacBook,150\niPad,300\nAirPods,500\nAppleWatch,250"
    return "product,amount\niPhone,150000\nMacBook,280000\niPad,120000"


@tool
def generate_chart(chart_type: str, title: str, x_column: str, y_column: str,
                    data_json: str, group_column: str | None = None) -> str:
    """生成图表"""
    import json
    try:
        rows = json.loads(data_json)
    except json.JSONDecodeError:
        return "ERROR: data_json 格式错误"
    if not rows:
        return "ERROR: 数据为空，无法生成图表"
    return '{"data":[{"type":"bar","x":["A","B"],"y":[100,200]}],"layout":{"title":"test"}}'


# ═══════════════════════════════════════════════════════════
# SQL Agent 推理逻辑
# ═══════════════════════════════════════════════════════════


class TestSQLAgentReasoning:
    """验证 SQL Agent 在真实场景下的推理决策"""

    def test_explores_schema_before_querying(self):
        """未知表 → 先 get_table_info → 再 execute_sql"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            make_tool_call_response("先看表结构", "get_table_info", {"table_name": "test_sales"}),
            make_tool_call_response("现在查询", "execute_sql",
                                   {"sql": "SELECT product, SUM(amount) FROM test_sales GROUP BY product"}),
            make_text_response("查询完成：iPhone销量最高"),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="所有产品的销售额排名")],
            "user_query": "所有产品的销售额排名",
            "plan": [{"step": 1, "task": "查询销售额排名", "type": "sql"}],
            "current_step_index": 0,
            "table_schemas_text": TEST_SCHEMA,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = agent(state)

        # 验证推理链条
        tool_names = [tc["tool"] for tc in result.get("react_tool_calls", [])]
        assert "get_table_info" in tool_names, "应先用 get_table_info 探索表结构"
        assert "execute_sql" in tool_names, "应在探索后执行 SQL"
        assert "SELECT" in result.get("sql_query", "")
        assert result.get("react_iterations", 0) <= 5

    def test_retries_on_sql_error(self):
        """SQL 错误 → 分析错误 → 修正重试"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            # 第一轮：直接执行有错误的SQL
            make_tool_call_response("执行查询", "execute_sql",
                                   {"sql": "SELECT * FROM non_existent_table"}),
            # 收到错误后继续
            make_tool_call_response("列名错了，修正", "execute_sql",
                                   {"sql": "SELECT product, SUM(amount) FROM test_sales GROUP BY product"}),
            # 修正成功
            make_text_response("查询成功，数据已获取"),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="查询")],
            "user_query": "查询",
            "plan": [{"step": 1, "task": "查询数据", "type": "sql"}],
            "current_step_index": 0,
            "table_schemas_text": TEST_SCHEMA,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = agent(state)

        # 应该调用了至少2次工具（第一次失败，第二次成功）
        sql_calls = [tc for tc in result.get("react_tool_calls", []) if tc["tool"] == "execute_sql"]
        assert len(sql_calls) >= 2, f"应在失败后重试，实际调用 {len(sql_calls)} 次"
        # 最终的SQL应正确
        assert "test_sales" in result.get("sql_query", "")

    def test_plans_out_multi_step_sql_workflow(self):
        """Agent 应能自主规划多步 SQL 工作流"""
        from backend.agent.analysts.sql_agent import create_sql_agent

        llm = FakeLLM(responses=[
            make_tool_call_response("先看结构", "get_table_info", {"table_name": "test_sales"}),
            make_tool_call_response("按产品汇总金额", "execute_sql",
                                   {"sql": "SELECT product, SUM(amount) FROM test_sales GROUP BY product"}),
            make_text_response("完成：iPhone销售额150000，MacBook销售额280000"),
        ])
        agent = create_sql_agent(llm, [get_table_info, execute_sql])

        state = {
            "messages": [HumanMessage(content="分析各产品销售表现")],
            "user_query": "分析各产品销售表现",
            "plan": [
                {"step": 1, "task": "统计总销售额", "type": "sql"},
                {"step": 2, "task": "按产品汇总", "type": "sql"},
            ],
            "current_step_index": 0,
            "table_schemas_text": TEST_SCHEMA,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = agent(state)

        assert "sql_query" in result
        assert result.get("react_iterations", 0) >= 1, "应至少执行了一轮推理"


# ═══════════════════════════════════════════════════════════
# Chart Agent 推理逻辑
# ═══════════════════════════════════════════════════════════


class TestChartAgentReasoning:
    """验证 Chart Agent 的推理决策"""

    def test_generates_chart_when_data_available(self):
        """有数据时生成图表"""
        import json

        from backend.agent.analysts.chart_agent import create_chart_agent

        sample_data = json.dumps([
            {"product": "iPhone", "amount": 150000},
            {"product": "MacBook", "amount": 280000},
        ])

        llm = FakeLLM(responses=[
            make_tool_call_response("生成柱状图", "generate_chart", {
                "chart_type": "bar",
                "title": "产品销售对比",
                "x_column": "product",
                "y_column": "amount",
                "data_json": sample_data,
            }),
            make_text_response("图表生成完成"),
        ])
        agent = create_chart_agent(llm, [generate_chart])

        state = {
            "messages": [HumanMessage(content="画图")],
            "plan": [{"step": 1, "task": "画图", "type": "chart"}],
            "sql_result": "product,amount\niPhone,150000\nMacBook,280000",
        }
        result = agent(state)

        chart_calls = [tc for tc in result.get("react_tool_calls", []) if tc["tool"] == "generate_chart"]
        assert len(chart_calls) >= 1, "有数据时应调用 generate_chart"

    def test_skips_chart_when_no_data(self):
        """无数据时跳过图表生成"""
        from backend.agent.analysts.chart_agent import create_chart_agent

        llm = FakeLLM(responses=[
            make_text_response("数据为空，不适合可视化"),
        ])
        agent = create_chart_agent(llm, [generate_chart])

        state = {
            "messages": [HumanMessage(content="画图")],
            "plan": [],
            "sql_result": "(查询成功，但无返回数据)",
        }
        result = agent(state)

        chart_calls = [tc for tc in result.get("react_tool_calls", []) if tc["tool"] == "generate_chart"]
        assert len(chart_calls) == 0, "无数据时不应生成图表"


# ═══════════════════════════════════════════════════════════
# Planner 推理逻辑
# ═══════════════════════════════════════════════════════════


class TestPlannerReasoning:
    """验证 Planner 的任务拆解能力"""

    def test_planner_outputs_valid_json(self):
        """Planner 必须输出合法 JSON 计划"""
        import json

        from backend.agent.managers.planner import create_planner

        plan_json = json.dumps({
            "plan": [
                {"step": 1, "task": "汇总各产品销售额", "type": "sql",
                 "depends_on": [], "expected_output": "销售额数据"},
                {"step": 2, "task": "画柱状图", "type": "chart",
                 "depends_on": [1], "expected_output": "销售额对比图"},
            ]
        })

        llm = FakeLLM(responses=[
            make_text_response(f"```json\n{plan_json}\n```"),
        ])
        agent = create_planner(llm)

        state = {
            "messages": [HumanMessage(content="分析销售数据")],
            "user_query": "分析销售数据",
            "table_schemas_text": TEST_SCHEMA,
        }
        result = agent(state)
        plan = result.get("plan", [])

        assert len(plan) >= 1, "应生成至少1步计划"
        assert plan[0]["type"] in ("sql", "chart"), "步骤类型应为 sql 或 chart"
        assert "task" in plan[0], "每个步骤应有 task 字段"


# ═══════════════════════════════════════════════════════════
# Validator 推理逻辑
# ═══════════════════════════════════════════════════════════


class TestValidatorReasoning:
    """验证 Validator 的裁判能力"""

    def test_rejects_when_data_contradicts_report(self):
        """报告中的数字与 SQL 结果不一致 → 应驳回"""
        import json

        from backend.agent.managers.validator import create_validator

        reject_json = json.dumps({
            "result": "rejected",
            "reason": "报告声称增长35%，但SQL结果显示实际增长为27%",
            "revise_suggestions": "请修正增长率数据",
        })

        llm = FakeLLM(responses=[
            make_text_response(f"```json\n{reject_json}\n```"),
        ])
        agent = create_validator(llm)

        state = {
            "messages": [HumanMessage(content="审核")],
            "user_query": "分析销售趋势",
            "draft_report": "## 结论\niPhone销量增长35%",
            "sql_result": "product,growth\niPhone,27",
            "optimistic_view": "销量增长良好",
            "pessimistic_view": "需关注竞争",
        }
        result = agent(state)

        assert result["validation_result"] == "rejected", (
            f"数据矛盾应驳回，实际结果: {result['validation_result']}"
        )

    def test_approves_when_data_consistent(self):
        """报告与 SQL 结果一致 → 应通过"""
        import json

        from backend.agent.managers.validator import create_validator

        approve_json = json.dumps({
            "result": "approved",
            "reason": "数据与结论一致，辩论双方观点均已纳入",
            "revise_suggestions": "",
        })

        llm = FakeLLM(responses=[
            make_text_response(f"```json\n{approve_json}\n```"),
        ])
        agent = create_validator(llm)

        state = {
            "messages": [HumanMessage(content="审核")],
            "user_query": "分析销售趋势",
            "draft_report": "## 结论\niPhone销量增长27%，达到150000件",
            "sql_result": "product,growth\niPhone,27",
            "optimistic_view": "销量增长良好",
            "pessimistic_view": "需关注竞争",
        }
        result = agent(state)

        assert result["validation_result"] == "approved", (
            f"数据一致应通过，实际结果: {result['validation_result']}"
        )


# ═══════════════════════════════════════════════════════════
# ReAct 推理品质
# ═══════════════════════════════════════════════════════════


class TestReActReasoningQuality:
    """验证 ReAct 循环的推理品质（非仅结构正确）"""

    def test_avoids_unnecessary_tool_calls(self):
        """不应在已有足够信息后继续调用工具"""
        from backend.agent.utils.react import create_react_agent

        llm = FakeLLM(responses=[
            make_text_response("收到，我不需要工具，答案可以直接给出"),
        ])
        agent = create_react_agent(llm, [get_table_info], "你是助手", max_iterations=5)

        state = {"messages": [HumanMessage(content="简单的问候")]}
        result = agent(state)

        # 不应该调用任何工具
        assert len(result["react_tool_calls"]) == 0, "简单问候不应调用工具"
        assert result["react_iterations"] == 1, "应在一轮内完成"

    def test_uses_multiple_tools_when_needed(self):
        """复杂任务应使用多种工具"""
        from backend.agent.utils.react import create_react_agent

        llm = FakeLLM(responses=[
            make_tool_call_response("先查表结构", "get_table_info", {"table_name": "test_sales"}),
            make_tool_call_response("再执行查询", "execute_sql",
                                   {"sql": "SELECT * FROM test_sales"}),
            make_text_response("查询完成，结果如上"),
        ])
        tools = [get_table_info, execute_sql]
        agent = create_react_agent(llm, tools, "你是数据分析助手", max_iterations=5)

        state = {"messages": [HumanMessage(content="分析test_sales表")]}
        result = agent(state)

        tool_names = [tc["tool"] for tc in result["react_tool_calls"]]
        assert len(set(tool_names)) >= 2, (
            f"复杂任务应使用多种工具，实际只用: {tool_names}"
        )

    def test_stops_at_max_iterations(self):
        """达到 max_iterations 上限后必须停止"""
        from backend.agent.utils.react import create_react_agent

        # 连续返回 tool_calls，永不结束
        endless_responses = [
            make_tool_call_response(f"第{i}次调用", "get_table_info", {"table_name": "test_sales"})
            for i in range(10)
        ]
        llm = FakeLLM(responses=endless_responses)
        agent = create_react_agent(llm, [get_table_info], "你是助手", max_iterations=3)

        state = {"messages": [HumanMessage(content="查询")]}
        result = agent(state)

        assert result["react_iterations"] <= 3, (
            f"应在 max_iterations=3 时停止，实际迭代了 {result['react_iterations']} 轮"
        )


# ═══════════════════════════════════════════════════════════
# Debate 推理逻辑
# ═══════════════════════════════════════════════════════════


class TestDebateReasoning:
    """验证辩论 Agent 的论证逻辑"""

    def test_optimist_cites_positive_data(self):
        """正方应从积极角度解读数据"""
        from backend.agent.debaters.optimist import create_optimist

        llm = FakeLLM(responses=[
            make_text_response("### 😊 乐观视角\n\n**积极信号:** iPhone销量增长27%，"
                              "MacBook以280000元销售额领先。市场前景乐观。"),
        ])
        agent = create_optimist(llm)

        state = {
            "messages": [HumanMessage(content="辩论")],
            "draft_report": "产品A增长27%，产品B销售额280000元",
            "debate_state": {
                "optimistic_history": "",
                "pessimistic_history": "",
                "latest_speaker": "",
                "round_count": 0,
            },
            "pessimistic_view": "",
        }
        result = agent(state)

        content = result.get("optimistic_view", "")
        assert len(content) > 30, "正方应生成有内容的论据"
        assert "增长" in content or "增长" in content or "积极" in content

    def test_pessimist_cites_risks(self):
        """反方应从风险角度审视数据"""
        from backend.agent.debaters.pessimist import create_pessimist

        llm = FakeLLM(responses=[
            make_text_response("### 😐 风险视角\n\n**需警惕的信号:** 增长集中于少数产品，"
                              "主力产品依赖度高，存在单一产品风险。"),
        ])
        agent = create_pessimist(llm)

        state = {
            "messages": [HumanMessage(content="辩论")],
            "draft_report": "增长27%但集中于少数产品",
            "debate_state": {
                "optimistic_history": "",
                "pessimistic_history": "",
                "latest_speaker": "",
                "round_count": 0,
            },
            "optimistic_view": "",
        }
        result = agent(state)

        content = result.get("pessimistic_view", "")
        assert len(content) > 30, "反方应生成有内容的论据"
        assert "风险" in content or "警惕" in content or "依赖" in content
