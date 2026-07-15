"""
集成测试 — FakeLLM + 真实 SQLiteStore + 真实 Tools + 多 Agent 编排

与 test_agent_reasoning.py 的区别:
  - test_agent_reasoning.py: FakeLLM + 假工具（Python 函数模拟）
  - 本文件: FakeLLM + 真实 backend.tools + 真实 SQLite + conftest fixtures

验证:
  1. SQL Agent 通过真实 execute_sql 查询真实 SQLite 数据
  2. Chart Agent 通过真实 generate_chart 生成图表 JSON
  3. 多 Agent 编排：Planner 产出计划 → SQL Agent 执行 → Chart Agent 可视化
  4. 条件路由：SQL 失败 → 重试 → 成功 → 进入下一阶段
  5. 全链路 state 传递：每个 Agent 正确读写 state 字段
"""

import json

from langchain_core.messages import HumanMessage

from backend.agent.analysts.chart_agent import create_chart_agent
from backend.agent.analysts.sql_agent import create_sql_agent
from backend.agent.managers.planner import create_planner
from backend.agent.synthesis.report_agent import create_report_agent
from backend.graph.conditional_logic import ConditionalLogic
from backend.graph.propagation import Propagator
from backend.tools import CHART_TOOLS, SQL_TOOLS, set_store
from tests.mock_llm import FakeLLM, make_text_response, make_tool_call_response

# ═══════════════════════════════════════════════════════════
# SQL Agent + 真实 SQLite + 真实 Tools
# ═══════════════════════════════════════════════════════════


class TestSQLAgentWithRealTools:
    """SQL Agent 通过真实的 execute_sql 工具操作真实 SQLite 数据库"""

    def test_queries_real_database(self, store_with_data):
        """FakeLLM 引导 SQL Agent 调用真实 execute_sql → 返回真实查询结果"""
        set_store(store_with_data)

        llm = FakeLLM(responses=[
            # 第1轮：查看表结构
            make_tool_call_response("先查表结构", "get_table_info", {"table_name": ""}),
            # 第2轮：执行真实查询
            make_tool_call_response("查询", "execute_sql",
                                   {"sql": "SELECT product, SUM(amount) as total FROM test_sales GROUP BY product ORDER BY total DESC"}),
            # 第3轮：总结
            make_text_response("查询完成，共5个产品，蓝牙耳机销售额最高"),
        ])

        agent = create_sql_agent(llm, list(SQL_TOOLS))
        schemas = store_with_data.get_schemas_text()

        state = {
            "messages": [HumanMessage(content="所有产品销售额排名")],
            "user_query": "所有产品销售额排名",
            "plan": [{"step": 1, "task": "产品销售额排名", "type": "sql"}],
            "current_step_index": 0,
            "table_schemas_text": schemas,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = agent(state)

        # 验证返回了真实的 SQL 结果
        assert "sql_result" in result
        assert result.get("sql_result") != ""
        assert "蓝牙耳机" in result.get("sql_result", "")
        assert result.get("react_iterations", 0) >= 1

    def test_sql_error_then_retry_with_real_tools(self, store_with_data):
        """SQL 错误（表不存在）→ Agent 修正 → 重试成功"""
        set_store(store_with_data)

        llm = FakeLLM(responses=[
            # 第1轮：错误的表名
            make_tool_call_response("查询", "execute_sql",
                                   {"sql": "SELECT * FROM non_existent_table"}),
            # 第2轮：查表结构后修正
            make_tool_call_response("先查表", "get_table_info", {"table_name": ""}),
            # 第3轮：用正确的表名重试
            make_tool_call_response("修正查询", "execute_sql",
                                   {"sql": "SELECT COUNT(*) FROM test_sales"}),
            # 第4轮：完成
            make_text_response("查询成功，test_sales 表共5行"),
        ])

        agent = create_sql_agent(llm, list(SQL_TOOLS))
        schemas = store_with_data.get_schemas_text()

        state = {
            "messages": [HumanMessage(content="统计行数")],
            "user_query": "统计行数",
            "plan": [{"step": 1, "task": "统计行数", "type": "sql"}],
            "current_step_index": 0,
            "table_schemas_text": schemas,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = agent(state)

        # 应该至少执行了2次 execute_sql（失败 + 重试）
        sql_calls = [tc for tc in result.get("react_tool_calls", []) if tc["tool"] == "execute_sql"]
        assert len(sql_calls) >= 2, f"应失败后重试，实际调用 {len(sql_calls)} 次"
        # 最终结果不应包含错误
        assert result.get("sql_result", "").startswith("ERROR") is False

    def test_multiple_steps_with_plan(self, store_with_data):
        """多步骤计划：第1步查总量 → ReAct 内部工具调用 → 返回结果"""
        set_store(store_with_data)
        schemas = store_with_data.get_schemas_text()

        # 第1步：先用 get_table_info 确认表，再 execute_sql
        llm = FakeLLM(responses=[
            make_tool_call_response("查看表", "get_table_info", {"table_name": "test_sales"}),
            make_tool_call_response("执行", "execute_sql",
                                   {"sql": "SELECT COUNT(*) as cnt FROM test_sales"}),
            make_text_response("第1步完成：test_sales 表共5行数据"),
        ])

        agent = create_sql_agent(llm, list(SQL_TOOLS))
        state = {
            "messages": [HumanMessage(content="统计")],
            "user_query": "统计",
            "plan": [{"step": 1, "task": "总行数", "type": "sql"}],
            "current_step_index": 0,
            "table_schemas_text": schemas,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        result = agent(state)

        # 应产生 SQL 结果
        assert "sql_result" in result
        # 至少有执行工具调用记录
        sql_calls = [tc for tc in result.get("react_tool_calls", []) if tc["tool"] == "execute_sql"]
        assert len(sql_calls) >= 1, "应至少调用一次 execute_sql"


# ═══════════════════════════════════════════════════════════
# Chart Agent + 真实 generate_chart 工具
# ═══════════════════════════════════════════════════════════


class TestChartAgentWithRealTools:
    """Chart Agent 通过真实的 generate_chart 工具生成图表"""

    def test_generates_real_plotly_json(self):
        """真实 generate_chart 工具 → 返回 Plotly JSON"""
        import json as _json

        sample_data = _json.dumps([
            {"product": "蓝牙耳机", "total": 28000},
            {"product": "手机壳", "total": 18000},
            {"product": "手机支架", "total": 15000},
            {"product": "充电宝", "total": 12000},
            {"product": "数据线", "total": 8000},
        ])

        llm = FakeLLM(responses=[
            make_tool_call_response("画柱状图", "generate_chart", {
                "chart_type": "bar",
                "title": "产品销售额对比",
                "x_column": "product",
                "y_column": "total",
                "data_json": sample_data,
            }),
            make_text_response("图表已生成"),
        ])

        agent = create_chart_agent(llm, list(CHART_TOOLS))
        state = {
            "messages": [HumanMessage(content="画图")],
            "plan": [{"step": 1, "task": "画图", "type": "chart"}],
            "sql_result": f"product,total\n{chr(10).join(f'{p},{a}' for p, a in [('蓝牙耳机', 28000), ('手机壳', 18000), ('手机支架', 15000), ('充电宝', 12000), ('数据线', 8000)])}",
        }
        result = agent(state)

        # chart_json 已从 ToolMessage 中提取（由 Chart Agent wrapper 处理）
        chart_calls = [tc for tc in result.get("react_tool_calls", []) if tc["tool"] == "generate_chart"]
        assert len(chart_calls) >= 1, "应调用 generate_chart 工具"
        # 结果预览应包含 Plotly JSON
        preview = chart_calls[0].get("result_preview", "")
        assert '"data"' in preview


# ═══════════════════════════════════════════════════════════
# 多 Agent 编排测试
# ═══════════════════════════════════════════════════════════


class TestMultiAgentOrchestration:
    """验证多 Agent 间的协作和数据传递"""

    def test_planner_to_sql_to_chart_to_report_chain(self, store_with_data):
        """完整链路: Planner → SQL Agent → Chart Agent → Report Agent"""
        set_store(store_with_data)
        schemas = store_with_data.get_schemas_text()

        # 1. Planner
        plan_json = json.dumps({
            "plan": [
                {"step": 1, "task": "各产品销售额汇总", "type": "sql",
                 "depends_on": [], "expected_output": "产品销售额数据"},
                {"step": 2, "task": "画柱状图", "type": "chart",
                 "depends_on": [1], "expected_output": "销售额对比图"},
            ]
        })
        planner_llm = FakeLLM(responses=[make_text_response(f"```json\n{plan_json}\n```")])
        planner = create_planner(planner_llm)

        planner_state = {
            "messages": [HumanMessage(content="分析销售数据")],
            "user_query": "分析销售数据",
            "table_schemas_text": schemas,
        }
        planner_result = planner(planner_state)
        assert len(planner_result["plan"]) == 2, "Planner 应产出2步计划"
        assert planner_result["plan"][0]["type"] == "sql"
        assert planner_result["plan"][1]["type"] == "chart"

        # 2. SQL Agent（使用计划第1步）
        sql_llm = FakeLLM(responses=[
            make_tool_call_response("执行查询", "execute_sql",
                                   {"sql": "SELECT product, SUM(amount) FROM test_sales GROUP BY product"}),
            make_text_response("查询完成，返回5个产品的销售额"),
        ])
        sql_agent = create_sql_agent(sql_llm, list(SQL_TOOLS))

        sql_state = {
            "messages": [HumanMessage(content="查询")],
            "user_query": "分析销售数据",
            "plan": planner_result["plan"],
            "current_step_index": 0,
            "table_schemas_text": schemas,
            "sql_result": "",
            "sql_error": "",
            "sql_retry_count": 0,
        }
        sql_result = sql_agent(sql_state)
        assert "sql_result" in sql_result
        assert "蓝牙耳机" in sql_result["sql_result"]

        # 3. Chart Agent（使用计划第2步 + SQL 结果）
        chart_llm = FakeLLM(responses=[
            make_tool_call_response("画图", "generate_chart", {
                "chart_type": "bar",
                "title": "产品销售额对比",
                "x_column": "product",
                "y_column": "total",
                "data_json": json.dumps([
                    {"product": "蓝牙耳机", "total": 28000},
                    {"product": "手机壳", "total": 18000},
                ]),
            }),
            make_text_response("图表完成"),
        ])
        chart_agent = create_chart_agent(chart_llm, list(CHART_TOOLS))

        chart_state = {
            "messages": [HumanMessage(content="画图")],
            "plan": planner_result["plan"],
            "sql_result": sql_result["sql_result"],
        }
        chart_result = chart_agent(chart_state)
        chart_calls = [tc for tc in chart_result.get("react_tool_calls", [])
                       if tc["tool"] == "generate_chart"]
        assert len(chart_calls) >= 1

        # 4. Report Agent（汇总 SQL + Chart）
        report_llm = FakeLLM(responses=[
            make_text_response("## 分析结论\n\n蓝牙耳机销售额最高，达到28000元。"
                             "其次是手机壳18000元。数据线销售额最低，仅8000元。"),
        ])
        report_agent = create_report_agent(report_llm)

        report_state = {
            "messages": [HumanMessage(content="写报告")],
            "user_query": "分析销售数据",
            "sql_query": sql_result.get("sql_query", ""),
            "sql_result": sql_result["sql_result"],
            "chart_json": {},
        }
        report_result = report_agent(report_state)
        assert len(report_result["draft_report"]) > 50
        assert "蓝牙耳机" in report_result["draft_report"]

    def test_conditional_routing_integration(self, store_with_data):
        """条件路由：SQL 错误 → 重试 → Msg Clear → Chart"""
        set_store(store_with_data)
        logic = ConditionalLogic(max_sql_retries=2, max_debate_rounds=2)

        # SQL 路由 — 正常完成
        state = {"messages": [], "sql_error": "", "sql_retry_count": 0}
        assert logic.should_continue_sql(state) == "Msg Clear SQL"

        # SQL 路由 — 有错误但未超限 → 重试
        class FakeMsg:
            tool_calls = []
        state = {"messages": [FakeMsg()], "sql_error": "no such column", "sql_retry_count": 0}
        assert logic.should_continue_sql(state) == "SQL Agent"

        # Validator 路由 — needs_review
        state = {"validation_result": "needs_review", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "END"

    def test_working_memory_flow_between_agents(self):
        """工作记忆在 Agent 间正确传递"""
        prop = Propagator()

        state = prop.create_initial_state(
            user_query="分析销售数据",
            available_tables=["test_sales"],
            table_schemas_text="Table: test_sales\nColumns: product(TEXT), amount(REAL)",
            agent_memory_context={"planner": "历史: 上次用 GROUP BY 查询"},
        )

        # 验证初始状态
        assert state["working_memory"]["findings"] == []
        assert "agent_memory_context" in state
        assert state["agent_memory_context"]["planner"] == "历史: 上次用 GROUP BY 查询"

        # 模拟 SQL Agent 添加发现
        state["working_memory"]["findings"].append({
            "agent": "sql_agent",
            "finding": "蓝牙耳机销售额最高：28000元",
            "confidence": 0.95,
        })
        state["sql_result"] = "product,total\n蓝牙耳机,28000\n手机壳,18000"

        # 验证下游 Agent 可以读取
        assert len(state["working_memory"]["findings"]) == 1
        assert state["working_memory"]["findings"][0]["confidence"] > 0.9

    def test_performance_tracking_across_agents(self):
        """性能数据跨越多个 Agent 节点累积"""
        from backend.graph.orchestrator import DataAgentGraph

        # 私有方法通过实例调用
        orch = DataAgentGraph.__new__(DataAgentGraph)

        timings = {
            "Planner": 1.5,
            "SQL Agent": 3.2,
            "Chart Agent": 2.1,
            "Report Agent": 1.8,
        }
        perf = orch._build_performance(timings, 15.0)

        assert perf["node_count"] == 4
        assert perf["total_time"] == 15.0
        assert perf["slowest_node"]["name"] == "SQL Agent"
        assert perf["fastest_node"]["name"] == "Planner"
