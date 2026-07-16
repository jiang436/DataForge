"""
ReAct Agent 工厂 — 让 Agent 真正拥有 think → act → observe 推理循环

参考: LangGraph 的 create_react_agent 预构建方法，手动实现以保持可控性。

核心差异 vs 原实现:
  原: Agent 只做一次 LLM 调用 → tool_calls 由外部 ToolNode 执行 → 路由决定是否继续
  新: Agent 内部维护 while 循环，每轮自主判断: 调用工具 / 输出最终答案

面试话术: "我手动实现了 ReAct 循环而非直接用 LangGraph 预构建的 create_react_agent，
         因为需要更精细地控制: 中间推理过程可追踪、工具调用可限次、异常可优雅降级。"
"""

import contextvars
import json
import logging
import time
from collections.abc import Callable

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# 最大 ReAct 迭代次数（防止无限循环）
DEFAULT_MAX_ITERATIONS = 5

_token_stream_ctx: contextvars.ContextVar = contextvars.ContextVar("token_stream_callback", default=None)


def set_token_stream_callback(cb: Callable | None):
    """设置 token 级流式回调（在 propagate 前调用）"""
    _token_stream_ctx.set(cb)


def get_token_stream_callback() -> Callable | None:
    """获取当前上下文的 token 流式回调"""
    return _token_stream_ctx.get()

REACT_SYSTEM_SUFFIX = """
## 推理规则（ReAct 模式）

你需要按照 **思考 → 行动 → 观察** 的循环来完成任务:

1. **思考**: 分析当前状态，判断下一步需要做什么
2. **行动**: 调用合适的工具获取信息
3. **观察**: 阅读工具返回的结果，更新你的理解
4. **重复**: 如果你还需要更多信息，继续循环

### 何时停止
当你已经收集了足够的信息来回答问题或完成任务时，输出你的最终答案。
**不要**在还有未执行的必要工具调用时输出最终答案。
**不要**循环超过 {max_iterations} 轮——如果工具返回异常，记录问题并给出你能给出的最佳答案。

### 当前进度
你已经执行了 {iteration_count} 轮推理，最多 {max_iterations} 轮。

{environment_context}
"""


def build_default_environment_context(state: dict) -> str:
    """
    构建运行时环境感知上下文（类似 IPython 命名空间快照）。

    从 state 中提取关键运行时信息，注入 LLM prompt，让 Agent 感知:
      - 前序步骤的执行结果
      - 当前已有的数据和错误
      - 剩余可用轮次

    借鉴: data_analysis_agent 的 IPython 状态化执行环境 —
          每轮推理前快照当前命名空间（变量、DataFrame、错误），
          让 LLM 感知"运行时状态"，减少重复查询和错误重试。

    Returns:
        环境快照文本，嵌入 ReAct system prompt
    """
    parts = []

    # ── SQL 相关状态 ──
    sql_result = state.get("sql_result", "")
    if sql_result and sql_result != "(查询成功，但无返回数据)":
        lines_count = len(sql_result.split("\n"))
        parts.append(f"- 上一轮 SQL 结果: {lines_count} 行数据")
    elif sql_result:
        parts.append("- 上一轮 SQL 结果: (无返回数据)")

    sql_error = state.get("sql_error", "")
    if sql_error:
        parts.append(f"- ⚠️ 上一轮 SQL 错误: {sql_error[:200]}")

    sql_query = state.get("sql_query", "")
    if sql_query:
        parts.append(f"- 已执行的 SQL: `{sql_query[:150]}{'...' if len(sql_query) > 150 else ''}`")

    # ── 图表状态 ──
    chart_json = state.get("chart_json")
    if chart_json:
        parts.append("- ✅ 图表已生成（Plotly JSON）")

    # ── 重试计数 ──
    retry_count = state.get("sql_retry_count", 0)
    if retry_count > 0:
        parts.append(f"- SQL 已重试 {retry_count} 次")

    # ── 剩余推理轮次 ──
    max_iter = state.get("_max_iterations", 5)
    current_iter = state.get("_current_iteration", 1)
    remaining = max(0, max_iter - current_iter)
    parts.append(f"- 剩余推理轮次: {remaining}/{max_iter}")

    # ── 计划进度 ──
    plan = state.get("plan", [])
    current_step = state.get("current_step_index", 0)
    if plan:
        parts.append(f"- 执行计划进度: 步骤 {current_step + 1}/{len(plan)}")

    if not parts:
        return "（初始状态，无历史上下文）"

    return "### 🔍 运行时环境快照\n" + "\n".join(parts)


def create_react_agent(
    llm: ChatOpenAI,
    tools: list,
    system_prompt: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tool_call_timeout: float = 30.0,
    stream_callback: Callable | None = None,
    environment_builder: Callable[[dict], str] | None = None,
):
    """
    创建 ReAct Agent 节点函数

    与原始 create_sql_agent/create_chart_agent 的区别:
      - 内部封装了完整的 think→act→observe 循环
      - Agent 自己决定调用哪些工具、何时停止
      - 每次工具调用的中间结果都写入 state，便于追踪
      - 支持环境感知上下文注入（每轮推理前快照运行时状态）

    Args:
        llm:             LLM 实例
        tools:           工具列表
        system_prompt:   系统提示词
        max_iterations:  最大推理轮数
        tool_call_timeout: 单次工具调用超时（秒）
        environment_builder: 可选的环境上下文构建函数(state) -> str
                             每轮推理前调用，返回运行时状态快照注入 prompt

    Returns:
        react_agent_node(state) -> dict  LangGraph 节点函数
    """
    tool_map = {tool.name: tool for tool in tools}

    # system_prompt 来自 .md 文件（可能含 { }），只用 str.format() 处理
    # REACT_SYSTEM_SUFFIX（我们完全控制），然后拼接，避免误替换用户 prompt 中的花括号

    # 绑定工具
    llm_with_tools = llm.bind_tools(tools)

    def react_agent_node(state: dict) -> dict:
        """LangGraph 节点函数 — 内部执行 ReAct 循环"""
        iteration_count = 0
        tool_call_history: list[dict] = []
        intermediate_steps: list[dict] = []
        start_time = time.time()

        # 构建初始消息（浅拷贝——LangChain Message 是不可变对象，浅拷贝足够安全）
        current_messages = [m for m in state.get("messages", [])]

        logger.info("[ReAct] 开始推理循环, 最大 %d 轮, 工具: %s",
                     max_iterations, list(tool_map.keys()))

        while iteration_count < max_iterations:
            iteration_count += 1

            # ─── 构建环境感知上下文 ───
            # 每轮推理前快照当前运行时状态，注入 prompt
            # 借鉴: data_analysis_agent 的 IPython 状态化执行环境
            env_ctx = ""
            if environment_builder:
                try:
                    env_ctx = environment_builder(state)
                except Exception as e:
                    logger.warning("[ReAct] 环境上下文构建失败: %s", e)
            else:
                # 默认使用内置环境构建器
                enriched = dict(state)
                enriched["_max_iterations"] = max_iterations
                enriched["_current_iteration"] = iteration_count
                try:
                    env_ctx = build_default_environment_context(enriched)
                except Exception as e:
                    logger.warning("[ReAct] 默认环境上下文构建失败: %s", e)

            # 将 system_prompt 与格式化后的 ReAct 后缀拼接
            # .format() 仅作用于 REACT_SYSTEM_SUFFIX（我们控制），不影响 system_prompt
            _sys_prompt = system_prompt + REACT_SYSTEM_SUFFIX.format(
                max_iterations=max_iterations,
                iteration_count=iteration_count,
                environment_context=env_ctx,
            )

            # 替换第一条 system message
            msgs = [SystemMessage(content=_sys_prompt)] + [
                m for m in current_messages if not isinstance(m, SystemMessage)
            ]

            logger.info("[ReAct] 第 %d/%d 轮推理", iteration_count, max_iterations)

            try:
                # 使用流式调用以支持 token 级输出
                stream_cb = stream_callback or get_token_stream_callback()
                if stream_cb:
                    full_content = ""
                    # 按 index 累积 tool_call delta（跨 chunk 分布时合并）
                    # 使用 tool_call_chunks 而非 tool_calls：
                    #   langchain-openai 会将 DeepSeek 逐字符流式 args 的每个部分 JSON
                    #   片段尝试解析为 dict，失败则得到 {}，导致 args 丢失。tool_call_chunks
                    #   保留了原始字符串片段，我们需要手动累积后解析完整 JSON。
                    tool_calls_raw: dict[int, dict] = {}
                    for chunk in llm_with_tools.stream(msgs):
                        c = getattr(chunk, "content", "")
                        if c:
                            full_content += c
                            try:
                                stream_cb(c)
                            except Exception:
                                pass
                        # 优先使用 tool_call_chunks（保留原始 args 字符串片段）
                        tc_chunks = getattr(chunk, "tool_call_chunks", None) or []
                        for tc in tc_chunks:
                            idx = tc.get("index", 0) or 0
                            if idx not in tool_calls_raw:
                                tool_calls_raw[idx] = {
                                    "name": tc.get("name") or "",
                                    "args_str": "",
                                    "id": tc.get("id") or "",
                                }
                            existing = tool_calls_raw[idx]
                            if tc.get("name"):
                                existing["name"] = tc["name"]
                            if tc.get("id"):
                                existing["id"] = tc["id"]
                            # 累积 args 字符串片段
                            args_val = tc.get("args")
                            if args_val:
                                existing["args_str"] += args_val if isinstance(args_val, str) else str(args_val)
                    # 解析累积的 args JSON 字符串 → dict
                    tool_calls_collected = []
                    for idx, v in sorted(tool_calls_raw.items()):
                        if not v["name"]:
                            continue
                        try:
                            parsed_args = json.loads(v["args_str"]) if v["args_str"].strip() else {}
                        except Exception:
                            logger.warning("[ReAct] 工具调用 args JSON 解析失败: %s", v["args_str"][:200])
                            parsed_args = {}
                        tool_calls_collected.append({
                            "name": v["name"],
                            "args": parsed_args,
                            "id": v["id"] or f"call_{idx}",
                            "type": "tool_call",
                        })
                    if tool_calls_collected:
                        response = AIMessage(content=full_content, tool_calls=tool_calls_collected)
                    else:
                        response = AIMessage(content=full_content)
                else:
                    response = llm_with_tools.invoke(msgs)
            except Exception as e:
                logger.error("[ReAct] LLM 调用失败 (第%d轮): %s", iteration_count, e)
                break

            current_messages.append(response)

            # 检查是否有 tool_calls
            has_tool_calls = (
                hasattr(response, "tool_calls")
                and response.tool_calls
            )

            if not has_tool_calls:
                # Agent 决定输出最终答案
                content = response.content if hasattr(response, "content") else str(response)
                logger.info("[ReAct] Agent 完成推理, %d 轮, 输出长度: %d",
                            iteration_count, len(content))
                intermediate_steps.append({
                    "iteration": iteration_count,
                    "action": "finish",
                    "output": content[:500],
                })
                break

            # 执行工具调用
            for tc in response.tool_calls:
                tool_name = tc.get("name", "unknown")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", f"call_{iteration_count}")

                logger.info("[ReAct] 调用工具: %s(%s)", tool_name,
                           str(tool_args)[:100])

                tool_fn = tool_map.get(tool_name)
                if tool_fn is None:
                    error_msg = f"未知工具: {tool_name}，可用: {list(tool_map.keys())}"
                    logger.warning("[ReAct] %s", error_msg)
                    tool_result = f"ERROR: {error_msg}"
                else:
                    try:
                        # 执行工具（带超时保护）
                        tool_result = tool_fn.invoke(tool_args)
                        if hasattr(tool_result, "content"):
                            tool_result = tool_result.content
                        elif not isinstance(tool_result, str):
                            tool_result = str(tool_result)
                    except Exception as e:
                        logger.error("[ReAct] 工具执行失败: %s", e)
                        tool_result = f"ERROR: {e}"

                # 记录工具调用历史
                call_record = {
                    "tool": tool_name,
                    "args": {k: str(v)[:200] for k, v in tool_args.items()},
                    "result_preview": str(tool_result)[:300],
                    "iteration": iteration_count,
                }
                tool_call_history.append(call_record)
                intermediate_steps.append({
                    "iteration": iteration_count,
                    "action": "tool_call",
                    "tool": tool_name,
                    "args_preview": str(tool_args)[:200],
                    "result_preview": str(tool_result)[:200],
                })

                # 将工具结果追加到消息历史
                current_messages.append(
                    ToolMessage(content=str(tool_result), tool_call_id=tool_id)
                )

        elapsed = time.time() - start_time
        logger.info("[ReAct] 推理完成: %d 轮, %.2fs, %d 次工具调用",
                    iteration_count, elapsed, len(tool_call_history))

        # 从消息中提取最终文本输出
        final_text = ""
        for msg in reversed(current_messages):
            if isinstance(msg, AIMessage) and not (hasattr(msg, "tool_calls") and msg.tool_calls):
                content = msg.content if hasattr(msg, "content") else str(msg)
                if content and len(content) > 20:
                    final_text = content
                    break

        return {
            "messages": current_messages,
            "react_intermediate_steps": intermediate_steps,
            "react_tool_calls": tool_call_history,
            "react_iterations": iteration_count,
            "react_elapsed": round(elapsed, 2),
            "react_final_output": final_text,
        }

    return react_agent_node


def extract_react_summary(state: dict, agent_name: str = "Agent") -> str:
    """从 ReAct 中间步骤生成可读摘要"""
    steps = state.get("react_intermediate_steps", [])
    if not steps:
        return f"[{agent_name}] 无推理步骤记录"

    lines = [f"## {agent_name} 推理过程"]
    for step in steps:
        if step.get("action") == "finish":
            lines.append(f"- 第{step['iteration']}轮: ✅ 完成推理")
        else:
            lines.append(
                f"- 第{step['iteration']}轮: 🔧 {step.get('tool', '?')}"
            )
    return "\n".join(lines)
