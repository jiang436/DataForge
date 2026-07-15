"""
FakeLLM — 用于测试的模拟 LLM，不依赖真实 API 调用。

支持:
  - 按 prompt 关键词匹配返回预设响应
  - 模拟 tool_calls 响应（测试 ReAct 循环）
  - 流式和非流式两种模式
  - 记录所有调用历史用于断言验证

用法:
    from tests.mock_llm import FakeLLM

    llm = FakeLLM(responses=[
        {"content": "SELECT * FROM sales", "tool_calls": [{"name": "execute_sql", ...}]},
        {"content": "查询完成，结果为..."},
    ])
    llm.bind_tools(tools)  # 返回自身（兼容 ChatOpenAI 接口）
    result = llm.invoke(messages)
    assert llm.call_count == 1
"""

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool


class FakeLLM(BaseChatModel):
    """
    模拟 LLM，按预设顺序返回响应。

    Attributes:
        responses: 预设响应列表，每个元素为 dict:
            - content: str — 文本内容
            - tool_calls: list[dict] | None — 模拟的 tool_calls
            - additional_kwargs: dict | None — 额外参数
        call_history: 每次 invoke/stream 调用的消息列表记录
        stream_mode: 是否启用流式模式
    """

    model_name: str = "fake-model"
    responses: list[dict[str, Any]] = []
    call_history: list[list[BaseMessage]] = []
    stream_mode: bool = False
    _bound_tools: list[BaseTool] = []

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        stream_mode: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.responses = responses or []
        self.call_history = []
        self.stream_mode = stream_mode
        self._bound_tools = []

    @property
    def call_count(self) -> int:
        return len(self.call_history)

    @property
    def last_call_messages(self) -> list[BaseMessage] | None:
        return self.call_history[-1] if self.call_history else None

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> ChatResult:
        self.call_history.append(list(messages))

        idx = min(self.call_count - 1, len(self.responses) - 1)
        if idx >= len(self.responses):
            # 超出预设响应范围，返回空响应
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

        resp = self.responses[idx]

        # 构建 AIMessage
        tool_calls = resp.get("tool_calls", [])
        additional_kwargs = resp.get("additional_kwargs", {})
        if tool_calls:
            additional_kwargs["tool_calls"] = tool_calls

        # AIMessage 不接受 tool_calls=None，空列表时不传此参数
        msg_kwargs: dict[str, Any] = {
            "content": resp.get("content", ""),
            "additional_kwargs": additional_kwargs,
        }
        if tool_calls:
            msg_kwargs["tool_calls"] = tool_calls

        msg = AIMessage(**msg_kwargs)

        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> Any:
        """流式输出：逐个 yield 内容块。"""
        self.call_history.append(list(messages))

        idx = min(self.call_count - 1, len(self.responses) - 1)
        if idx >= len(self.responses):
            yield AIMessage(content="")
            return

        resp = self.responses[idx]
        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls")

        # 模拟逐 chunk 输出 content
        chunk_size = max(1, len(content) // 4) if content else 1
        for i in range(0, len(content), chunk_size):
            chunk_text = content[i : i + chunk_size]
            # 如果是最后一个 chunk 且有 tool_calls，附加到最后一个 chunk
            is_last = i + chunk_size >= len(content)
            if is_last and tool_calls:
                yield AIMessage(content=chunk_text, tool_calls=tool_calls)
            else:
                yield AIMessage(content=chunk_text)

        if not content and tool_calls:
            yield AIMessage(content="", tool_calls=tool_calls)

    def bind_tools(self, tools: list, **kwargs) -> "FakeLLM":
        """兼容 ChatOpenAI.bind_tools() 接口，返回自身。"""
        self._bound_tools = list(tools)
        return self

    def invoke(self, input: Any, config=None, **kwargs) -> Any:
        """重写 invoke 以正确处理消息列表输入和 Runnable config。"""
        if isinstance(input, list):
            result = self._generate(input, **kwargs)
            return result.generations[0].message
        return super().invoke(input, config, **kwargs)

    def stream(self, input: Any, **kwargs) -> Any:
        """重写 stream 以正确返回生成器。"""
        if isinstance(input, list):
            return self._stream(input, **kwargs)
        return super().stream(input, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "fake-llm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name}


# ─── 预置响应工厂函数 ───


def make_text_response(content: str) -> dict:
    """纯文本响应（无 tool_calls）。"""
    return {"content": content, "tool_calls": []}


def make_tool_call_response(content: str, tool_name: str, tool_args: dict) -> dict:
    """带单个 tool_call 的响应。"""
    return {
        "content": content,
        "tool_calls": [
            {
                "name": tool_name,
                "args": tool_args,
                "id": f"call_test_{tool_name}",
                "type": "tool_call",
            }
        ],
    }


def make_multi_tool_call_response(
    content: str, calls: list[tuple[str, dict]]
) -> dict:
    """带多个 tool_calls 的响应。"""
    return {
        "content": content,
        "tool_calls": [
            {
                "name": name,
                "args": args,
                "id": f"call_test_{name}_{i}",
                "type": "tool_call",
            }
            for i, (name, args) in enumerate(calls)
        ],
    }
