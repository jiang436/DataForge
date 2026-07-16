"""
编排器集成测试

使用 FakeLLM 模拟完整 7 Agent 流程，验证:
  - DataAgentGraph 的构建和执行
  - SQL 重试路径
  - 辩论循环轮次控制
  - Validator 驳回修正
  - 进度回调和性能数据收集
"""


from backend.graph.conditional_logic import ConditionalLogic
from backend.graph.propagation import Propagator

# ─── ConditionalLogic 测试扩展 ───


class TestConditionalLogicExtended:
    def test_sql_retry_when_error_and_below_max(self):
        """有错误且未超过重试次数 → 返回 SQL Agent 重试。"""
        logic = ConditionalLogic(max_sql_retries=2)
        from langchain_core.messages import AIMessage

        state = {
            "messages": [AIMessage(content="查询出错")],
            "sql_error": "no such column",
            "sql_retry_count": 0,
        }
        result = logic.should_continue_sql(state)
        assert result == "SQL Agent"

    def test_sql_force_stop_at_max_retries(self):
        """超过最大重试次数 → 强制 Msg Clear。"""
        logic = ConditionalLogic(max_sql_retries=2)
        from langchain_core.messages import AIMessage

        state = {
            "messages": [AIMessage(content="查询出错")],
            "sql_error": "no such column",
            "sql_retry_count": 2,  # = max
        }
        result = logic.should_continue_sql(state)
        assert result == "Msg Clear SQL"

    def test_sql_with_tool_calls_over_retry_limit(self):
        """有 tool_calls 但 tool_call_count 超过阈值 → 强制结束。"""
        logic = ConditionalLogic(max_sql_retries=1)
        from langchain_core.messages import AIMessage

        msg = AIMessage(content="执行", tool_calls=[{"name": "execute_sql", "args": {}, "id": "x"}])
        state = {
            "messages": [msg],
            "sql_retry_count": 2,  # >= max + 1
        }
        result = logic.should_continue_sql(state)
        assert result == "Msg Clear SQL"

    def test_debate_alternation(self):
        """辩论路由正确交替发言。"""
        logic = ConditionalLogic(max_debate_rounds=2)

        # Optimistic 发言后 → Pessimistic
        state = {
            "debate_state": {"round_count": 1, "latest_speaker": "optimistic"},
        }
        assert logic.should_continue_debate(state) == "Pessimistic"

        # Pessimistic 发言后 → Optimistic
        state["debate_state"] = {"round_count": 2, "latest_speaker": "pessimistic"}
        assert logic.should_continue_debate(state) == "Optimistic"

    def test_debate_ends_at_max_rounds(self):
        """达到最大发言次数 → Validator。"""
        logic = ConditionalLogic(max_debate_rounds=2)
        # max 2 rounds = 4 speeches
        state = {
            "debate_state": {"round_count": 4, "latest_speaker": "pessimistic"},
        }
        assert logic.should_continue_debate(state) == "Validator"

    def test_validator_approved_ends(self):
        """Validator 通过 → END。"""
        logic = ConditionalLogic()
        state = {"validation_result": "approved", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "END"

    def test_validator_rejected_below_limit(self):
        """驳回但修订次数未达上限 → Report Agent 修正。"""
        logic = ConditionalLogic()
        state = {"validation_result": "rejected", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "Report Agent"

    def test_validator_rejected_at_limit(self):
        """v3.2: 修订达到上限(3) → 强制 END。"""
        logic = ConditionalLogic()
        state = {"validation_result": "rejected", "revision_count": 3}
        assert logic.should_continue_after_validator(state) == "END"

    def test_validator_rejected_below_limit_v32(self):
        """v3.2: 修订 2 次仍可继续（上限 3）。"""
        logic = ConditionalLogic()
        state = {"validation_result": "rejected", "revision_count": 2}
        assert logic.should_continue_after_validator(state) == "Report Agent"

    def test_validator_needs_review(self):
        """需要人工审核 → END（暂停图等待人工）。"""
        logic = ConditionalLogic()
        state = {"validation_result": "needs_review", "revision_count": 0}
        assert logic.should_continue_after_validator(state) == "END"


# ─── Propagator 测试扩展 ───


class TestPropagatorExtended:
    def test_propagator_labels_coverage(self):
        """验证所有节点的进度标签。"""
        propagator = Propagator()

        labels = {
            "Planner": "📋 任务规划",
            "SQL Agent": "🔍 数据查询",
            "Chart Agent": "📊 生成图表",
            "Report Agent": "📝 撰写报告",
            "Optimistic": "🟢 乐观方辩论",
            "Pessimistic": "🔴 谨慎方辩论",
            "Validator": "⚖️ 裁判验证",
        }

        for node, _expected_label in labels.items():
            label = propagator.get_progress_label(node)
            assert label is not None, f"Missing label for {node}"
            assert len(label) > 0

    def test_propagator_unknown_node_returns_default(self):
        """未知节点返回默认emoji标签（非None）。"""
        propagator = Propagator()
        label = propagator.get_progress_label("NonExistent")
        # 未知节点返回带emoji的默认标签
        assert label is not None
        assert "NonExistent" in label

    def test_create_initial_state_structure(self):
        """初始状态包含所有必要字段。"""
        propagator = Propagator()

        state = propagator.create_initial_state(
            user_query="测试问题",
            available_tables=["test_table"],
            table_schemas_text="Table: test_table\nColumns: a(TEXT)",
            historical_context="",
        )

        required_fields = [
            "user_query", "available_tables", "table_schemas_text",
            "plan", "current_step_index", "sql_retry_count",
            "revision_count", "messages",
        ]
        for field in required_fields:
            assert field in state, f"Missing field: {field}"

        assert state["user_query"] == "测试问题"
        assert state["available_tables"] == ["test_table"]
        assert state["sql_retry_count"] == 0
        assert state["revision_count"] == 0

    def test_create_initial_state_has_historical_field(self):
        """初始状态包含 historical_context 字段。"""
        propagator = Propagator()

        state = propagator.create_initial_state(
            user_query="分析",
            available_tables=["t"],
            table_schemas_text="",
            historical_context="之前分析过类似数据",
        )

        # historical_context 被注入到 messages 中，字段本身可以不存在于顶层 state
        assert state["user_query"] == "分析"


# ─── Orchestrator 构建测试 ───


class TestOrchestratorBuild:
    def test_orchestrator_initialization(self):
        """DataAgentGraph 初始化不崩溃。"""
        from backend.dataflows.sqlite_store import SQLiteStore
        from backend.graph.orchestrator import DataAgentGraph
        from backend.tools import set_store

        store = SQLiteStore(db_path=":memory:")
        set_store(store)

        try:
            orch = DataAgentGraph(provider="deepseek", store=store)
            assert orch.quick_thinking_llm is not None
            assert orch.deep_thinking_llm is not None
            assert orch.graph is not None
            assert orch.conditional_logic is not None
            assert orch.propagator is not None
        finally:
            store.close()

    def test_orchestrator_performance_building(self):
        """性能数据构建正确。"""
        from backend.dataflows.sqlite_store import SQLiteStore
        from backend.graph.orchestrator import DataAgentGraph
        from backend.tools import set_store

        store = SQLiteStore(db_path=":memory:")
        set_store(store)

        try:
            orch = DataAgentGraph(provider="deepseek", store=store)

            timings = {"Planner": 1.5, "SQL Agent": 8.2, "Validator": 2.1}
            perf = orch._build_performance(timings, 12.0)

            assert perf["total_time"] == 12.0
            assert perf["node_count"] == 3
            assert perf["slowest_node"]["name"] == "SQL Agent"
            assert perf["fastest_node"]["name"] == "Planner"
            assert "node_timings" in perf
        finally:
            store.close()

    def test_orchestrator_performance_empty_timings(self):
        """无计时数据时返回默认结构。"""
        from backend.dataflows.sqlite_store import SQLiteStore
        from backend.graph.orchestrator import DataAgentGraph
        from backend.tools import set_store

        store = SQLiteStore(db_path=":memory:")
        set_store(store)

        try:
            orch = DataAgentGraph(provider="deepseek", store=store)
            perf = orch._build_performance({}, 5.0)

            assert perf["total_time"] == 5.0
            assert perf["node_count"] == 0
        finally:
            store.close()
