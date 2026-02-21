"""条件路由测试"""

from backend.graph.conditional_logic import ConditionalLogic


def make_state(**kwargs):
    """创建模拟 state"""
    defaults = {
        "messages": [],
        "sql_retry_count": 0,
        "sql_error": "",
        "sql_result": "",
        "debate_state": {
            "latest_speaker": "",
            "round_count": 0,
            "optimistic_history": "",
            "pessimistic_history": "",
        },
        "validation_result": "approved",
        "revision_count": 0,
    }
    defaults.update(kwargs)
    return defaults


class TestSQLRouting:
    def setup_method(self):
        self.logic = ConditionalLogic(max_sql_retries=2)

    def test_no_messages_goes_to_clear(self):
        state = make_state()
        assert self.logic.should_continue_sql(state) == "Msg Clear SQL"

    def test_tool_calls_goes_to_tools(self):
        class FakeMsg:
            tool_calls = [{"name": "execute_sql"}]
        state = make_state(messages=[FakeMsg()])
        assert self.logic.should_continue_sql(state) == "tools_sql"

    def test_error_causes_retry(self):
        class FakeMsg:
            tool_calls = []
        state = make_state(
            messages=[FakeMsg()],
            sql_error="no such column",
            sql_retry_count=0,
        )
        assert self.logic.should_continue_sql(state) == "SQL Agent"

    def test_max_retries_exceeded(self):
        class FakeMsg:
            tool_calls = []
        state = make_state(
            messages=[FakeMsg()],
            sql_error="no such column",
            sql_retry_count=2,
        )
        assert self.logic.should_continue_sql(state) == "Msg Clear SQL"

    def test_max_tool_calls_exceeded(self):
        class FakeMsg:
            tool_calls = [{"name": "execute_sql"}]
        state = make_state(messages=[FakeMsg()], sql_retry_count=3)
        assert self.logic.should_continue_sql(state) == "Msg Clear SQL"


class TestDebateRouting:
    def setup_method(self):
        self.logic = ConditionalLogic(max_debate_rounds=2)

    def test_first_round_optimistic(self):
        state = make_state(
            debate_state={
                "latest_speaker": "",
                "round_count": 0,
                "optimistic_history": "",
                "pessimistic_history": "",
            }
        )
        assert self.logic.should_continue_debate(state) == "Optimistic"

    def test_alternating(self):
        state = make_state(
            debate_state={
                "latest_speaker": "optimistic",
                "round_count": 1,
                "optimistic_history": "",
                "pessimistic_history": "",
            }
        )
        assert self.logic.should_continue_debate(state) == "Pessimistic"

    def test_max_rounds_ends_debate(self):
        state = make_state(
            debate_state={
                "latest_speaker": "pessimistic",
                "round_count": 4,
                "optimistic_history": "",
                "pessimistic_history": "",
            }
        )
        assert self.logic.should_continue_debate(state) == "Validator"


class TestValidatorRouting:
    def setup_method(self):
        self.logic = ConditionalLogic()

    def test_approved_ends(self):
        state = make_state(validation_result="approved")
        assert self.logic.should_continue_after_validator(state) == "END"

    def test_rejected_goes_back(self):
        state = make_state(validation_result="rejected", revision_count=0)
        assert self.logic.should_continue_after_validator(state) == "Report Agent"

    def test_max_revisions_ends(self):
        state = make_state(validation_result="rejected", revision_count=2)
        assert self.logic.should_continue_after_validator(state) == "END"
