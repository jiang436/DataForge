"""
Planner Agent — 任务规划

负责:
  拿到用户问题 → 理解数据表结构 → 拆解为可执行的步骤清单

角色类比: 原项目的 Research Manager（决策型 Agent）
LLM 策略: 使用 deep_think_llm（温度 0.3，长输出），需要全面推理

v3.0 变更:
  - 主路径使用 with_structured_output(PlanResult) 消除 JSON 解析失败
  - 保留 free-text + parse_llm_json 作为降级路径
"""

import json
import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.agent.schemas import PlanResult
from backend.agent.utils.state import DataAnalysisState
from backend.prompts import load_prompt
from backend.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = load_prompt("planner")


def create_planner(llm):
    """
    创建 Planner 节点函数

    参考: tradingagents/agents/managers/research_manager.py
    工厂模式: 外部注入 llm → 返回闭包给 LangGraph 调用

    Args:
        llm: deep_think_llm 实例

    Returns:
        planner_node(state) -> dict  可用于 workflow.add_node()
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", PLANNER_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    chain = prompt | llm

    def planner_node(state: DataAnalysisState) -> dict:
        """LangGraph 节点函数"""
        logger.info("[Planner] 开始规划任务: %s", state["user_query"][:100])

        # 构建调用参数
        invoke_args = {
            "messages": state["messages"],
            "table_schemas": state.get("table_schemas_text", ""),
        }

        plan = []

        # ─── 主路径: structured output ───
        try:
            structured_chain = prompt | llm.with_structured_output(
                PlanResult, method="json_schema"
            )
            result = structured_chain.invoke(invoke_args)
            plan = [s.model_dump() for s in result.plan]
            logger.info("[Planner] Structured output 成功, 共 %d 步", len(plan))
        except (AttributeError, NotImplementedError, TypeError) as e:
            logger.info("[Planner] Structured output 不可用 (%s)，使用 free-text 解析", e)
            plan = _fallback_parse(chain, invoke_args, state)
        except Exception as e:
            logger.warning("[Planner] Structured output 失败 (%s)，降级到 free-text 解析", e)
            plan = _fallback_parse(chain, invoke_args, state)

        logger.info("[Planner] 计划生成完成，共 %d 步", len(plan))

        # 生成进度消息
        step_descriptions = "\n".join(f"  第{s.get('step', i+1)}步: {s.get('task', '?')}" for i, s in enumerate(plan))
        progress = f"📋 任务拆解完成，共 {len(plan)} 步:\n{step_descriptions}"

        # 构造 AIMessage（无论哪条路径都保证消息存在）
        from langchain_core.messages import AIMessage
        response = AIMessage(content=json.dumps({"plan": plan}, ensure_ascii=False))

        return {
            "plan": plan,
            "current_step_index": 0,
            "progress_message": progress,
            "messages": [response],
        }

    return planner_node


def _fallback_parse(chain, invoke_args: dict, state: dict) -> list[dict]:
    """Free-text JSON 解析降级路径。返回 plan 列表。"""
    response = chain.invoke(invoke_args)
    content = response.content if hasattr(response, "content") else str(response)

    try:
        parsed = parse_llm_json(content, description="Planner 输出")
        # LLM 可能输出 {"plan": [...]} 或直接输出 [...]
        if isinstance(parsed, list):
            return parsed
        else:
            return parsed.get("plan", [])
    except (ValueError, json.JSONDecodeError) as e:
        logger.error("[Planner] JSON 解析失败: %s，使用默认计划", e)
        return [
            {
                "step": 1,
                "task": state["user_query"],
                "type": "sql",
                "expected_output": "查询结果",
            }
        ]
