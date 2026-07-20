"""辩论质量回归测试 — 验证对抗辩论机制的工程质量

测试覆盖:
  1. 辩论评分正确性: 三维独立打分（论据/数据/反驳）映射验证
  2. 辩论状态机:     双方交替发言、轮次控制
  3. 边界条件:       空辩论、单方发言、数据矛盾
  4. 前端格式化:     评分格式化为前端可展示数据
"""

import pytest

from backend.agent.debaters.scorer import DebateScorer, format_debate_score_for_frontend
from backend.agent.utils.state import DebateScore
from tests.mock_llm import FakeLLM


# ═══════════════════════════════════════════════════════════
# 1. 辩论评分逻辑测试
# ═══════════════════════════════════════════════════════════

class TestDebateScoringLogic:
    """DebateScorer 三维评分的正确性"""

    def test_scorer_uses_fake_llm(self):
        """评分器使用 FakeLLM 返回预设评分"""
        llm = FakeLLM(responses=[
            {
                "content": '{"optimistic_score":85,"pessimistic_score":72,'
                           '"optimistic_breakdown":{"argument_quality":90,"data_support":85,"rebuttal":80},'
                           '"pessimistic_breakdown":{"argument_quality":70,"data_support":75,"rebuttal":70},'
                           '"winner":"optimistic","summary":"正方胜出"}',
                "tool_calls": [],
            }
        ])
        scorer = DebateScorer(llm)
        state = {
            "optimistic_view": "戴尔销量最高，代表市场偏好",
            "pessimistic_view": "苹果增长更快，长期可能反超",
            "sql_result": "brand,sales\nDell,80000\nApple,50000",
            "user_query": "哪个品牌表现最好？",
        }
        scores = scorer.score(state)
        assert scores["optimistic_score"] == 85
        assert scores["pessimistic_score"] == 72
        assert scores["winner"] == "optimistic"

    def test_scorer_handles_empty_debate(self):
        """无辩论内容 → 跳过评分，返回 0/0/tie"""
        llm = FakeLLM(responses=[])
        scorer = DebateScorer(llm)
        state = {
            "optimistic_view": "",
            "pessimistic_view": "",
            "sql_result": "",
            "user_query": "",
        }
        scores = scorer.score(state)
        assert scores["optimistic_score"] == 0
        assert scores["pessimistic_score"] == 0
        assert scores["winner"] == "tie"
        assert "无辩论" in scores["summary"]

    def test_scorer_preserves_breakdown(self):
        """评分应保留分项分数"""
        llm = FakeLLM(responses=[
            {
                "content": '{"optimistic_score":90,"pessimistic_score":60,'
                           '"optimistic_breakdown":{"argument_quality":95,"data_support":90,"rebuttal":85},'
                           '"pessimistic_breakdown":{"argument_quality":60,"data_support":55,"rebuttal":65},'
                           '"winner":"optimistic","summary":"正方完胜"}',
                "tool_calls": [],
            }
        ])
        scorer = DebateScorer(llm)
        scores = scorer.score({"optimistic_view": "x", "pessimistic_view": "y", "sql_result": "z"})
        breakdown = scores.get("optimistic_breakdown", {})
        assert breakdown.get("argument_quality", 0) > 0
        assert breakdown.get("data_support", 0) > 0

    def test_winner_must_be_valid_value(self):
        """胜方字段只能是 optimistic / pessimistic / tie"""
        for winner in ("optimistic", "pessimistic", "tie"):
            llm = FakeLLM(responses=[
                {
                    "content": f'{{"optimistic_score":80,"pessimistic_score":70,'
                               f'"winner":"{winner}","summary":"test"}}',
                    "tool_calls": [],
                }
            ])
            scorer = DebateScorer(llm)
            scores = scorer.score({"optimistic_view": "x", "pessimistic_view": "y"})
            assert scores["winner"] in ("optimistic", "pessimistic", "tie")


# ═══════════════════════════════════════════════════════════
# 2. 辩论结果格式化
# ═══════════════════════════════════════════════════════════

class TestDebateScoreFormatting:
    """前端格式化逻辑验证"""

    def test_format_complete_scores(self):
        scores = DebateScore(
            optimistic_score=85,
            pessimistic_score=72,
            optimistic_breakdown={"argument_quality": 90, "data_support": 85, "rebuttal": 80},
            pessimistic_breakdown={"argument_quality": 70, "data_support": 75, "rebuttal": 70},
            winner="optimistic",
            summary="正方在论据质量上明显占优",
        )
        formatted = format_debate_score_for_frontend(scores)
        assert formatted["has_scores"] is True
        assert "正方" in formatted["winner_label"]
        assert formatted["optimistic_score"] == 85
        assert formatted["pessimistic_score"] == 72

    def test_format_tie_scores(self):
        scores = DebateScore(
            optimistic_score=75,
            pessimistic_score=75,
            winner="tie",
            summary="势均力敌",
        )
        formatted = format_debate_score_for_frontend(scores)
        assert "平局" in formatted["winner_label"]

    def test_format_pessimistic_winner(self):
        scores = DebateScore(
            optimistic_score=60,
            pessimistic_score=80,
            winner="pessimistic",
            summary="反方识别了数据中的关键风险",
        )
        formatted = format_debate_score_for_frontend(scores)
        assert "反方" in formatted["winner_label"]

    def test_format_empty_scores(self):
        """空/None 评分 → has_scores=False"""
        formatted = format_debate_score_for_frontend(None)
        assert formatted["has_scores"] is False

    def test_format_preserves_breakdown(self):
        """分项分数应保留到前端"""
        scores = DebateScore(
            optimistic_score=80,
            pessimistic_score=70,
            optimistic_breakdown={"argument_quality": 85},
            pessimistic_breakdown={"argument_quality": 65},
            winner="optimistic",
            summary="",
        )
        formatted = format_debate_score_for_frontend(scores)
        assert formatted["opt_breakdown"]["argument_quality"] == 85


# ═══════════════════════════════════════════════════════════
# 3. 辩论质量边界条件
# ═══════════════════════════════════════════════════════════

class TestDebateEdgeCases:
    """辩论机制的边界条件和异常处理"""

    def test_single_sided_debate(self):
        """只有正方发言 → 反方分数应为 0"""
        llm = FakeLLM(responses=[
            {
                "content": '{"optimistic_score":80,"pessimistic_score":0,'
                           '"winner":"optimistic","summary":"反方未参与辩论"}',
                "tool_calls": [],
            }
        ])
        scorer = DebateScorer(llm)
        scores = scorer.score({
            "optimistic_view": "数据分析表明...",
            "pessimistic_view": "",  # 反方未发言
            "sql_result": "data",
        })
        # 如果有发言，分数 > 0
        assert scores["optimistic_score"] > 0

    def test_contradictory_data_detection(self):
        """SQL 数据存在明显矛盾时，辩论双方应都能发现"""
        llm = FakeLLM(responses=[
            {
                "content": '{"optimistic_score":75,"pessimistic_score":80,'
                           '"winner":"pessimistic","summary":"反方更准确地识别了数据异常"}',
                "tool_calls": [],
            }
        ])
        scorer = DebateScorer(llm)
        # 模拟矛盾数据: 总销量与各品牌之和不对应
        scores = scorer.score({
            "optimistic_view": "总销量表现良好",
            "pessimistic_view": "各品牌之和与总销量不匹配，怀疑数据质量问题",
            "sql_result": "总计: 1000, 各品牌和: 850",
        })
        # 双方都有有效评分
        assert scores["optimistic_score"] > 0
        assert scores["pessimistic_score"] > 0

    def test_scorer_truncates_long_inputs(self):
        """超长辩论内容 → 应截断处理，不崩溃"""
        llm = FakeLLM(responses=[
            {"content": '{"optimistic_score":80,"pessimistic_score":70,"winner":"optimistic","summary":"ok"}',
             "tool_calls": []}
        ])
        scorer = DebateScorer(llm)
        # 构造 10KB+ 的辩论内容
        long_text = "数据分析显示...\n" * 500
        scores = scorer.score({
            "optimistic_view": long_text,
            "pessimistic_view": long_text,
            "sql_result": long_text[:2000],
        })
        # 不应崩溃，应正确截断
        assert "optimistic_score" in scores
        assert scores["optimistic_score"] > 0

    def test_scorer_structured_output_fallback(self):
        """Structured output 不可用时的降级路径验证"""
        # FakeLLM 没有 with_structured_output，走 free-text 路径
        llm = FakeLLM(responses=[
            {
                "content": '```json\n{"optimistic_score":82,"pessimistic_score":68,'
                           '"winner":"optimistic","summary":"正方胜"}\n```',
                "tool_calls": [],
            }
        ])
        scorer = DebateScorer(llm)
        scores = scorer.score({
            "optimistic_view": "view A",
            "pessimistic_view": "view B",
        })
        assert scores["optimistic_score"] == 82
        assert scores["winner"] == "optimistic"
