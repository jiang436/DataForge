"""
ReAct Agent 循环测试

验证 think→act→observe 推理循环的核心行为:
  1. 正常结束（无 tool_calls → 输出最终答案）
  2. 达到 max_iterations 上限后强制停止
  3. 工具调用 → 观察 → 继续推理的完整循环
  4. 未知工具的错误处理
  5. 流式回调被正确调用
  6. 中间步骤记录完整性
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from backend.agent.utils.react import create_react_agent, extract_react_summary
from tests.mock_llm import FakeLLM, make_text_response, make_tool_call_response

# ─── 测试工具 ───


@tool
def echo(text: str) -> str:
    """返回输入文本"""
    return f"ECHO: {text}"


@tool
def add(a: int, b: int) -> str:
    """返回两数之和"""
    return str(a + b)


# ─── ReAct 正常完成 ───


def test_react_completes_when_no_tool_calls():
    """Agent 在 LLM 不再返回 tool_calls 时正常结束。"""
    llm = FakeLLM(responses=[make_text_response("分析完成，最终结果为42，这是通过综合计算得出的结论。")])
    agent = create_react_agent(llm, [echo], "你是一个助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="帮我分析")]}
    result = agent(state)

    assert llm.call_count == 1
    assert result["react_iterations"] == 1
    assert "42" in result["react_final_output"]
    assert len(result["react_intermediate_steps"]) == 1
    assert result["react_intermediate_steps"][0]["action"] == "finish"


def test_react_completes_after_tool_then_answer():
    """Agent 调用一次工具后，下一轮给出最终答案。"""
    llm = FakeLLM(responses=[
        make_tool_call_response("让我查一下", "echo", {"text": "hello"}),
        make_text_response("查询结果是 ECHO: hello，分析完成。"),
    ])
    agent = create_react_agent(llm, [echo], "你是一个助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="帮我查询")]}
    result = agent(state)

    assert llm.call_count == 2
    assert result["react_iterations"] == 2
    assert len(result["react_tool_calls"]) == 1
    assert result["react_tool_calls"][0]["tool"] == "echo"
    assert "ECHO: hello" in result["react_tool_calls"][0]["result_preview"]


# ─── 最大迭代次数 ───


def test_react_stops_at_max_iterations():
    """超过 max_iterations 后强制停止，不无限循环。"""
    # 每轮都返回 tool_calls，永远不输出最终答案
    responses = [
        make_tool_call_response("再查一次", "echo", {"text": "loop"})
        for _ in range(10)
    ]
    llm = FakeLLM(responses=responses)
    agent = create_react_agent(llm, [echo], "你是一个助手", max_iterations=3)

    state = {"messages": [HumanMessage(content="无限查询")]}
    result = agent(state)

    assert result["react_iterations"] == 3
    assert len(result["react_tool_calls"]) == 3


def test_react_stops_at_max_iterations_default():
    """使用默认 max_iterations=5 时正确停止。"""
    responses = [
        make_tool_call_response("查", "echo", {"text": "x"})
        for _ in range(10)
    ]
    llm = FakeLLM(responses=responses)
    agent = create_react_agent(llm, [echo], "助手")

    state = {"messages": [HumanMessage(content="查询")]}
    result = agent(state)

    assert result["react_iterations"] <= 5
    assert len(result["react_tool_calls"]) <= 5


# ─── 多工具调用 ───


def test_react_multiple_tools_in_one_turn():
    """单轮 LLM 响应中可能包含多个 tool_calls。"""
    llm = FakeLLM(responses=[
        {
            "content": "需要查两个东西",
            "tool_calls": [
                {"name": "echo", "args": {"text": "a"}, "id": "call_1", "type": "tool_call"},
                {"name": "add", "args": {"a": 1, "b": 2}, "id": "call_2", "type": "tool_call"},
            ],
        },
        make_text_response("都查到了。"),
    ])
    agent = create_react_agent(llm, [echo, add], "助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="查两个东西")]}
    result = agent(state)

    assert result["react_iterations"] == 2
    assert len(result["react_tool_calls"]) == 2
    tool_names = [tc["tool"] for tc in result["react_tool_calls"]]
    assert "echo" in tool_names
    assert "add" in tool_names


# ─── 错误处理 ───


def test_react_handles_unknown_tool():
    """调用不存在的工具时返回错误信息，不崩溃。"""
    llm = FakeLLM(responses=[
        {
            "content": "试试未知工具",
            "tool_calls": [
                {"name": "nonexistent_tool", "args": {}, "id": "call_bad", "type": "tool_call"}
            ],
        },
        make_text_response("那个工具不存在，我用其他方式帮你。"),
    ])
    agent = create_react_agent(llm, [echo], "助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="测试")]}
    result = agent(state)

    # 不应崩溃
    assert result["react_iterations"] >= 1
    # 工具调用记录中应有错误信息
    error_record = result["react_tool_calls"][0]
    assert "ERROR" in error_record["result_preview"] or "未知" in error_record["result_preview"]


def test_react_handles_tool_execution_error():
    """工具执行抛出异常时不崩溃，继续循环。"""
    @tool
    def failing_tool(x: str) -> str:
        """这个工具总是失败。"""
        raise ValueError("模拟工具执行失败")

    llm = FakeLLM(responses=[
        make_tool_call_response("试试", "failing_tool", {"x": "test"}),
        make_text_response("工具失败了，但我给你手动分析..."),
    ])
    agent = create_react_agent(llm, [failing_tool], "助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="测试")]}
    result = agent(state)

    assert "ERROR" in result["react_tool_calls"][0]["result_preview"]


# ─── 流式回调 ───


def test_react_stream_callback_called():
    """验证流式回调在每块 token 输出时被调用。"""
    tokens_received: list[str] = []

    def on_token(t: str):
        tokens_received.append(t)

    llm = FakeLLM(
        responses=[make_text_response("Hello World from streaming")],
        stream_mode=True,
    )
    agent = create_react_agent(
        llm, [echo], "助手", max_iterations=5, stream_callback=on_token,
    )

    state = {"messages": [HumanMessage(content="hi")]}
    agent(state)

    assert len(tokens_received) > 0
    assert "".join(tokens_received) == "Hello World from streaming"


def test_react_stream_contextvar_callback():
    """验证通过 contextvars 设置的流式回调也能工作。"""
    from backend.agent.utils.react import set_token_stream_callback

    tokens_received: list[str] = []

    def on_token(t: str):
        tokens_received.append(t)

    set_token_stream_callback(on_token)

    llm = FakeLLM(
        responses=[make_text_response("ContextVar test")],
        stream_mode=True,
    )
    agent = create_react_agent(llm, [echo], "助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="test")]}
    agent(state)

    assert len(tokens_received) > 0

    # 清理
    set_token_stream_callback(None)


# ─── 中间步骤记录 ───


def test_react_records_intermediate_steps():
    """验证每轮的中间步骤都被正确记录。"""
    llm = FakeLLM(responses=[
        make_tool_call_response("第一步：查数据", "echo", {"text": "data"}),
        make_tool_call_response("第二步：再加一个查询", "add", {"a": 3, "b": 4}),
        make_text_response("综合分析完成。"),
    ])
    agent = create_react_agent(llm, [echo, add], "助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="分析")]}
    result = agent(state)

    steps = result["react_intermediate_steps"]
    assert len(steps) == 3

    # 前两步是 tool_call
    assert steps[0]["action"] == "tool_call"
    assert steps[1]["action"] == "tool_call"
    # 第三步是 finish
    assert steps[2]["action"] == "finish"


def test_react_tool_call_history_format():
    """验证 tool_call_history 的格式完整性。"""
    llm = FakeLLM(responses=[
        make_tool_call_response("查一下", "echo", {"text": "test_value"}),
        make_text_response("完成"),
    ])
    agent = create_react_agent(llm, [echo], "助手", max_iterations=5)

    state = {"messages": [HumanMessage(content="查询")]}
    result = agent(state)

    tc = result["react_tool_calls"][0]
    assert tc["tool"] == "echo"
    assert "test_value" in tc["args"].get("text", "")
    assert "result_preview" in tc
    assert tc["iteration"] == 1


# ─── 状态恢复 ───


def test_react_preserves_existing_messages():
    """ReAct agent 在已有消息历史上追加，不丢失原有消息。"""
    llm = FakeLLM(responses=[make_text_response("收到，继续。")])
    agent = create_react_agent(llm, [echo], "助手", max_iterations=5)

    existing = [HumanMessage(content="问题1"), AIMessage(content="回答1")]
    state = {"messages": list(existing)}
    result = agent(state)

    # 返回的消息包含原有 + 新增
    assert len(result["messages"]) > len(existing)


# ─── extract_react_summary ───


def test_extract_react_summary():
    """验证从 state 提取推理摘要。"""
    state = {
        "react_intermediate_steps": [
            {"iteration": 1, "action": "tool_call", "tool": "echo"},
            {"iteration": 2, "action": "finish", "output": "分析完毕"},
        ]
    }
    summary = extract_react_summary(state, "TestAgent")
    assert "TestAgent" in summary
    assert "echo" in summary
    assert "完成" in summary


def test_extract_react_summary_empty():
    """无推理步骤时返回默认信息。"""
    state = {"react_intermediate_steps": []}
    summary = extract_react_summary(state, "Agent")
    assert "无推理步骤记录" in summary
