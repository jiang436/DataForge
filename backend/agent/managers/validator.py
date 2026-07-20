"""
Validator Judge — 最终裁判

负责:
  辩论结束后 → 检查三方一致性（数据↔图表↔报告结论）
  → 对辩论双方独立评分 → 判断报告是否可用 → 通过/驳回

角色类比: 原项目的 Research Manager 和 Risk Judge
LLM 策略: deep_think_llm，需要仔细核对一致性

v3.0 变更:
  - 主路径使用 with_structured_output(ValidationResult) 消除 JSON 解析失败
  - 保留 free-text + parse_llm_json 作为降级路径
  - 保留 VALIDATOR_RETRY_PROMPT 重试机制

裁判标准:
  1. 数据一致性: 报告中的数字是否与 SQL 结果一致？
  2. 逻辑一致性: 图表趋势是否与结论一致？
  3. 辩论质量: 双方观点是否都被纳入考量？
  4. 完整性: 是否遗漏了关键信息？
"""

import json
import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.agent.schemas import ValidationResult
from backend.agent.utils.state import DataAnalysisState
from backend.prompts import load_prompt
from backend.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)

VALIDATOR_SYSTEM_PROMPT = load_prompt("validator")

VALIDATOR_RETRY_PROMPT = """你上一次的输出格式不正确，无法解析为 JSON。

请严格按照以下格式重新输出（只输出 JSON，不要加解释或 markdown 标记）:

{"result": "approved", "reason": "...", "revise_suggestions": ""}

你的上一次输出是:
{previous_output}

请重新裁判。只输出 JSON。
"""


def _parse_validator_output(content: str) -> dict:
    """
    解析 Validator 输出（使用共享解析器）

    返回: {"result": "approved"/"rejected"/"needs_review", "reason": "...", "revise_suggestions": "..."}
    """
    parsed = parse_llm_json(content, description="Validator 输出")
    if not isinstance(parsed, dict):
        raise ValueError(f"Validator 应输出 JSON 对象，实际为: {type(parsed).__name__}")
    return parsed


def _validate_result(parsed: dict) -> dict:
    """校验并规范化解析结果

    v3.2: 新增 approved_with_suggestions（通过但附优化建议）
    """
    result = parsed.get("result", "rejected")

    # approved / approved_with_suggestions / rejected 是有效值
    if result in ("approved", "approved_with_suggestions", "rejected"):
        pass
    elif "reject" in str(result).lower() or "驳回" in str(result):
        result = "rejected"
    elif "suggest" in str(result).lower() or "建议" in str(result):
        # "approved_with_suggestions" 的各种变体
        result = "approved_with_suggestions"
    elif "approve" in str(result).lower() or "通过" in str(result):
        result = "approved"
    else:
        result = "needs_review"

    return {
        "result": result,
        "reason": parsed.get("reason", "未知原因"),
        "revise_suggestions": parsed.get("revise_suggestions", ""),
    }


def create_validator(llm):
    """
    创建 Validator 节点函数


    v3.0 改进:
      - 主路径: with_structured_output(ValidationResult) → 确定性类型化输出
      - 降级: 保留 free-text + parse_llm_json 解析路径
      - 降级: 保留 VALIDATOR_RETRY_PROMPT 重试机制
      - 解析失败默认 rejected（安全性优先）
      - 支持 needs_review 状态（Human-in-the-loop）
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", VALIDATOR_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])

    chain = prompt | llm

    def validator_node(state: DataAnalysisState) -> dict:
        """LangGraph 节点函数"""
        logger.info("[Validator] 开始裁判验证")

        sql_result = state.get("sql_result", "")
        sql_snippet = sql_result[:1500] if len(sql_result) > 1500 else sql_result

        # 格式化辩论评分
        debate_scores = state.get("debate_scores")
        if debate_scores:
            ds_text = (
                f"正方: {debate_scores.get('optimistic_score', '?')}/100, "
                f"反方: {debate_scores.get('pessimistic_score', '?')}/100, "
                f"胜方: {debate_scores.get('winner', '?')}"
            )
        else:
            ds_text = "(未评分)"

        invoke_args = {
            "messages": state["messages"],
            "user_query": state.get("user_query", ""),
            "draft_report": state.get("draft_report", "")[:3000],
            "optimistic_view": state.get("optimistic_view", "")[:1500],
            "pessimistic_view": state.get("pessimistic_view", "")[:1500],
            "sql_result": sql_snippet,
            "debate_scores": ds_text,
        }

        # ─── 解析裁判结果 ───
        result = "rejected"  # 默认驳回（安全性优先）
        reason = ""
        response = None

        # 主路径: structured output（消除 JSON 解析失败）
        try:
            structured_chain = prompt | llm.with_structured_output(
                ValidationResult, method="json_schema"
            )
            validated_obj = structured_chain.invoke(invoke_args)
            validated = validated_obj.model_dump()
            result = validated["result"]
            reason = validated["reason"]
            suggestions = validated.get("revise_suggestions", "")
            if suggestions:
                reason += f"。建议: {suggestions[:200]}"
            logger.info("[Validator] Structured output 成功, 结果: %s", result)
        except (AttributeError, NotImplementedError, TypeError) as e:
            logger.info("[Validator] Structured output 不可用 (%s)，使用 free-text 解析", e)
            # 降级路径
            response = chain.invoke(invoke_args)
            content = response.content if hasattr(response, "content") else str(response)
            result, reason = _fallback_parse(content, llm)
        except Exception as e:
            logger.warning("[Validator] Structured output 失败 (%s)，降级到 free-text 解析", e)
            response = chain.invoke(invoke_args)
            content = response.content if hasattr(response, "content") else str(response)
            result, reason = _fallback_parse(content, llm)

        logger.info("[Validator] 裁判结果: %s, 理由: %s", result, reason[:100])

        # 确定最终报告和进度消息
        prev_revision = state.get("revision_count", 0)

        if result == "approved":
            final_report = state.get("draft_report", "")
            progress = "✅ Validator: 报告已通过验证"
        elif result == "approved_with_suggestions":
            final_report = state.get("draft_report", "")
            progress = f"💡 Validator: 报告通过（附优化建议）\n{reason[:200]}"
        elif result == "rejected":
            final_report = state.get("draft_report", "")
            progress = f"❌ Validator: 报告需修正 (第{prev_revision + 1}次)\n理由: {reason[:200]}"
        else:  # needs_review
            final_report = state.get("draft_report", "")
            progress = f"⚠️ Validator: 需要人工审核\n理由: {reason[:200]}"

        # 如果 structured output 路径产生了 response，用它；否则用已有的
        if response is None and result:
            # structured output 成功时没有 AIMessage，构造一个
            from langchain_core.messages import AIMessage
            response = AIMessage(content=f"裁判结果: {result}. {reason}")

        return {
            "validation_result": result,
            "validation_reason": reason,
            "revision_count": prev_revision + 1 if result == "rejected" else prev_revision,
            "final_report": final_report,
            "progress_message": progress,
            "messages": [response] if response else [],
        }

    return validator_node


def _fallback_parse(content: str, llm) -> tuple[str, str]:
    """
    Free-text JSON 解析降级路径（保留 v2.0 的重试逻辑）。
    返回 (result, reason)
    """
    try:
        parsed = _parse_validator_output(content)
        validated = _validate_result(parsed)
        result = validated["result"]
        reason = validated["reason"]
        suggestions = validated.get("revise_suggestions", "")
        if suggestions:
            reason += f"。建议: {suggestions[:200]}"
        return result, reason
    except (ValueError, json.JSONDecodeError, AttributeError) as e:
        logger.warning("[Validator] JSON 解析失败 (第1次): %s, 原始输出: %s", e, content[:300])
        # 重试
        try:
            retry_content = VALIDATOR_RETRY_PROMPT.format(previous_output=content[:500])
            retry_response = llm.invoke(retry_content)
            retry_text = retry_response.content if hasattr(retry_response, "content") else str(retry_response)

            parsed = _parse_validator_output(retry_text)
            validated = _validate_result(parsed)
            result = validated["result"]
            reason = validated["reason"] + " (重试后解析)"
            revise = validated.get("revise_suggestions", "")
            if revise:
                reason += f"。建议: {revise[:200]}"
            logger.info("[Validator] 重试解析成功, 结果: %s", result)
            return result, reason
        except Exception as e2:
            logger.error("[Validator] JSON 解析重试也失败: %s, 设为 needs_review", e2)
            return "needs_review", f"Validator 输出格式异常，无法自动解析。原始输出: {content[:500]}"
