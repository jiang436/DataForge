"""状态传播测试"""

from backend.graph.propagation import Propagator


class TestPropagator:
    def setup_method(self):
        self.p = Propagator(max_recur_limit=50)

    def test_create_initial_state(self):
        state = self.p.create_initial_state(
            user_query="test query",
            available_tables=["sales", "orders"],
            table_schemas_text="Table: sales\nTable: orders",
        )
        assert state["user_query"] == "test query"
        assert state["available_tables"] == ["sales", "orders"]
        assert "Table: sales" in state["table_schemas_text"]
        assert state["plan"] == []
        assert state["sql_result"] == ""
        assert state["debate_state"]["round_count"] == 0
        assert state["revision_count"] == 0

    def test_initial_state_has_messages(self):
        state = self.p.create_initial_state(
            user_query="q",
            available_tables=[],
            table_schemas_text="",
        )
        assert len(state["messages"]) > 0

    def test_historical_context_injected(self):
        state = self.p.create_initial_state(
            user_query="分析Q3",
            available_tables=[],
            table_schemas_text="T",
            historical_context="## 历史经验\n经验1",
        )
        msg_content = state["messages"][0].content
        assert "历史经验" in msg_content or "经验1" in msg_content

    def test_get_graph_args_with_progress(self):
        args = self.p.get_graph_args(use_progress_callback=True)
        assert args["stream_mode"] == "updates"
        assert args["config"]["recursion_limit"] == 50

    def test_get_graph_args_without_progress(self):
        args = self.p.get_graph_args(use_progress_callback=False)
        assert args["stream_mode"] == "values"

    def test_progress_labels(self):
        assert "Planner" in self.p.PROGRESS_LABELS
        assert self.p.get_progress_label("Planner") is not None
        assert self.p.get_progress_label("Unknown") is not None

    def test_progress_label_format(self):
        label = self.p.get_progress_label("SQL Agent")
        assert isinstance(label, str)
        assert len(label) > 0
