"""
辩论评分器 — 对正反方辩论质量进行量化评分

v3.0 变更:
  - 主路径使用 with_structured_output(DebateScoreResult) 消除 JSON 解析失败
  - 保留 free-text + parse_llm_json 作为降级路径

评分体系: 论据质量(40%) + 数据支撑(40%) + 反驳力度(20%)，对辩论双方独立打分。
"""

import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.agent.schemas import DebateScoreResult
from backend.agent.utils.state import DebateScore
from backend.prompts import load_prompt
from backend.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)

DEBATE_SCORER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", load_prompt("debate_scorer")),
])


class DebateScorer:
    """
    辩论评分器

    用法:
        scorer = DebateScorer(llm)
        scores = scorer.score(state)
        # scores = {"optimistic_score": 82, "pessimistic_score": 78, "winner": "optimistic", ...}
    """

    def __init__(self, llm: ChatOpenAI):
        self.llm = llm
        self.chain = DEBATE_SCORER_PROMPT | llm

    def score(self, state: dict) -> DebateScore:
        """
        对辩论进行评分

        Args:
            state: 包含 optimistic_view, pessimistic_view, sql_result 的 state

        Returns:
            DebateScore 字典
        """
        opt_view = state.get("optimistic_view", "")
        pess_view = state.get("pessimistic_view", "")

        if not opt_view and not pess_view:
            logger.info("[辩论评分] 无辩论内容，跳过评分")
            return DebateScore(
                optimistic_score=0,
                pessimistic_score=0,
                winner="tie",
                summary="无辩论内容",
            )

        sql_result = state.get("sql_result", "")
        sql_summary = sql_result[:500] if len(sql_result) > 500 else sql_result

        invoke_args = {
            "user_query": state.get("user_query", "")[:300],
            "sql_summary": sql_summary,
            "optimistic_view": opt_view[:2000],
            "pessimistic_view": pess_view[:2000],
        }

        # ─── 主路径: structured output ───
        try:
            structured_chain = DEBATE_SCORER_PROMPT | self.llm.with_structured_output(
                DebateScoreResult, method="json_schema"
            )
            result = structured_chain.invoke(invoke_args)
            parsed = result.model_dump()
            logger.info("[辩论评分] Structured output 成功")
        except (AttributeError, NotImplementedError, TypeError) as e:
            logger.info("[辩论评分] Structured output 不可用 (%s)，使用 free-text 解析", e)
            response = self.chain.invoke(invoke_args)
            content = response.content if hasattr(response, "content") else str(response)
            parsed = self._parse_json(content)
        except Exception as e:
            logger.warning("[辩论评分] Structured output 失败 (%s)，降级到 free-text 解析", e)
            response = self.chain.invoke(invoke_args)
            content = response.content if hasattr(response, "content") else str(response)
            parsed = self._parse_json(content)

        scores = DebateScore(
            optimistic_score=parsed.get("optimistic_score", 0),
            pessimistic_score=parsed.get("pessimistic_score", 0),
            optimistic_breakdown=parsed.get("optimistic_breakdown", {}),
            pessimistic_breakdown=parsed.get("pessimistic_breakdown", {}),
            winner=parsed.get("winner", "tie"),
            summary=parsed.get("summary", "评分失败"),
        )

        logger.info(
            "[辩论评分] 正方=%d 反方=%d 胜方=%s",
            scores["optimistic_score"],
            scores["pessimistic_score"],
            scores["winner"],
        )
        return scores

    def _parse_json(self, content: str) -> dict:
        """解析 LLM 输出的 JSON（使用共享解析器）"""
        return parse_llm_json(content, description="辩论评分输出")


def format_debate_score_for_frontend(scores: DebateScore) -> dict:
    """将辩论评分格式化为前端可展示的数据"""
    if not scores:
        return {"has_scores": False}

    winner_label = {
        "optimistic": "🌱 正方（乐观方）胜出",
        "pessimistic": "🛡️ 反方（谨慎方）胜出",
        "tie": "🤝 平局",
    }

    return {
        "has_scores": True,
        "winner": scores.get("winner", "tie"),
        "winner_label": winner_label.get(scores.get("winner", "tie"), "平局"),
        "optimistic_score": scores.get("optimistic_score", 0),
        "pessimistic_score": scores.get("pessimistic_score", 0),
        "opt_breakdown": scores.get("optimistic_breakdown", {}),
        "pess_breakdown": scores.get("pessimistic_breakdown", {}),
        "summary": scores.get("summary", ""),
    }
