"""
评估框架测试

验证各 Agent 的输出质量评估逻辑:
  - SQL 评估：正确 SQL 得高分，错误 SQL 得低分
  - 报告评估：幻觉检测、结构评分、数据引用检测
  - 图表评估：有数据无图表 vs 无数据有图表
  - 综合评估：多 Agent 加权总分计算
"""

from backend.eval.metrics import (
    evaluate_chart_agent,
    evaluate_debate_quality,
    evaluate_overall,
    evaluate_report_agent,
    evaluate_sql_agent,
)


class TestSQLEvaluation:
    def test_correct_sql_scores_high(self):
        """正确执行且返回数据的 SQL 得分应接近 1.0。"""
        state = {
            "sql_query": "SELECT * FROM sales",
            "sql_result": "name,amount\nA,100\nB,200\nC,300",
            "sql_error": "",
            "react_iterations": 1,
        }
        ev = evaluate_sql_agent(state)
        assert ev.score >= 0.8
        assert ev.metrics["sql_syntax_valid"] == 1.0
        assert ev.metrics["result_non_empty"] == 1.0

    def test_sql_error_scores_low(self):
        """SQL 执行错误得分应较低。"""
        state = {
            "sql_query": "SELECT * FROM nonexistent",
            "sql_result": "",
            "sql_error": "no such table: nonexistent",
            "react_iterations": 2,
        }
        ev = evaluate_sql_agent(state)
        assert ev.score < 0.6
        assert ev.metrics["sql_syntax_valid"] == 0.0
        assert len(ev.warnings) >= 1

    def test_empty_result_scores_partial(self):
        """查询成功但无数据时 result_non_empty 得分较低。"""
        state = {
            "sql_query": "SELECT * FROM sales WHERE 1=0",
            "sql_result": "(查询成功，但无返回数据)",
            "sql_error": "",
            "react_iterations": 1,
        }
        ev = evaluate_sql_agent(state)
        assert ev.metrics["result_non_empty"] == 0.3

    def test_no_sql_warning(self):
        """未生成 SQL 时应有警告。"""
        state = {
            "sql_query": "",
            "sql_result": "",
            "sql_error": "",
            "react_iterations": 1,
        }
        ev = evaluate_sql_agent(state)
        assert len(ev.warnings) >= 1

    def test_many_iterations_penalizes_efficiency(self):
        """ReAct 迭代次数多时 efficiency 得分降低。"""
        state = {
            "sql_query": "SELECT 1",
            "sql_result": "1",
            "sql_error": "",
            "react_iterations": 6,
        }
        ev = evaluate_sql_agent(state)
        assert ev.metrics["iterations_efficiency"] < 1.0


class TestReportEvaluation:
    def test_quality_report_scores_high(self):
        """结构完整、引用数据的报告得分高。"""
        state = {
            "draft_report": (
                "## 分析结论\n\n"
                "根据查询结果，总销售额为 43,000 元，同比增长 15%。"
                "从数据分析可以看出，各品牌表现差异明显。"
                "其中品牌A以15000元位居销售额榜首，市场份额约35%。"
                "品牌B紧随其后，销售额为28000元，占比约65%。"
                "整体市场呈现稳步增长态势。\n\n"
                "| 品牌 | 销售额 | 市场份额 | 增长率 |\n"
                "|------|--------|----------|--------|\n"
                "| A | 15000 | 35% | 12% |\n"
                "| B | 28000 | 65% | 18% |\n\n"
                "- 品牌A表现稳定，但增速略低于品牌B\n"
                "- 品牌B增长显著，主要是降价促销推动\n"
                "- 建议品牌A加强渠道投入以缩小增速差距"
            ),
        }
        ev = evaluate_report_agent(state)
        assert ev.score >= 0.6
        # 报告长度 > 300 字符
        assert ev.metrics["min_length"] > 0.8
        assert ev.metrics["structure"] >= 0.7

    def test_short_report_scores_low(self):
        """过短的报告得分低。"""
        state = {"draft_report": "销售额是100元。"}
        ev = evaluate_report_agent(state)
        assert ev.score < 0.5
        assert len(ev.warnings) >= 1

    def test_hallucination_detection(self):
        """包含假设性用语的报告得分降低。"""
        state = {
            "draft_report": (
                "## 分析\n\n假设有100个用户，典型数据表明增长趋势。"
                "假如价格降低10%，销量可能提升。"
            ),
        }
        ev = evaluate_report_agent(state)
        assert ev.metrics["no_hallucination"] < 1.0

    def test_no_structure_warning(self):
        """缺少 Markdown 结构的报告有警告。"""
        state = {"draft_report": "这是一个没有结构的纯文本报告，销售额为100元。"}
        ev = evaluate_report_agent(state)
        assert len(ev.warnings) >= 1


class TestChartEvaluation:
    def test_chart_generated_scores_high(self):
        """有数据且生成了图表应得高分。"""
        state = {
            "chart_json": {"data": [{"type": "bar"}]},
            "sql_result": "name,amount\nA,100\nB,200",
            "react_iterations": 1,
        }
        ev = evaluate_chart_agent(state)
        assert ev.score >= 0.8
        assert ev.metrics["chart_generated"] == 1.0

    def test_no_chart_with_data_warns(self):
        """有数据但未生成图表时警告。"""
        state = {
            "chart_json": None,
            "sql_result": "name,amount\nA,100\nB,200",
            "react_iterations": 1,
        }
        ev = evaluate_chart_agent(state)
        assert len(ev.warnings) >= 1

    def test_chart_without_data_flag(self):
        """无数据时不应生成图表（可能是编造）。"""
        state = {
            "chart_json": {"data": [{"type": "bar"}]},
            "sql_result": "(查询成功，但无返回数据)",
            "react_iterations": 1,
        }
        ev = evaluate_chart_agent(state)
        # 有图表但没有数据支撑 → 有警告
        assert len(ev.warnings) >= 1


class TestDebateEvaluation:
    def test_both_sides_participated_scores_high(self):
        """双方都参与辩论且引用数据得分高。"""
        state = {
            "optimistic_view": "正面：该品牌销量最高，增长达20%，好评率92%",
            "pessimistic_view": "反面：折扣率最低，仅为8%，保修期只有12个月",
            "debate_scores": {"optimistic_score": 85, "pessimistic_score": 72},
        }
        ev = evaluate_debate_quality(state)
        assert ev.score >= 0.7
        assert ev.metrics["both_sides_participated"] == 1.0

    def test_missing_side_scores_low(self):
        """一方未发言时得分低。"""
        state = {
            "optimistic_view": "",
            "pessimistic_view": "只有反方发言",
            "debate_scores": None,
        }
        ev = evaluate_debate_quality(state)
        assert ev.score < 0.5
        assert len(ev.warnings) >= 1

    def test_no_data_support_warning(self):
        """辩论中缺乏数据支撑时警告。"""
        state = {
            "optimistic_view": "这个品牌很好，很优秀，值得推荐",
            "pessimistic_view": "这个品牌不好，有风险，不建议购买",
            "debate_scores": {},
        }
        ev = evaluate_debate_quality(state)
        # 没有具体数据引用，data_supported 应偏低
        assert ev.metrics["data_supported"] < 0.5


class TestOverallEvaluation:
    def test_overall_evaluation_structure(self):
        """综合评估返回完整结构。"""
        state = {
            "sql_query": "SELECT 1",
            "sql_result": "1",
            "sql_error": "",
            "react_iterations": 1,
            "draft_report": "## 报告\n\n销售额为 15000 元。",
            "chart_json": {"data": [{"type": "bar"}]},
            "optimistic_view": "正方：数据表明增长趋势",
            "pessimistic_view": "反方：需要注意风险",
            "debate_scores": {"optimistic_score": 80, "pessimistic_score": 70},
        }
        result = evaluate_overall(state)

        assert "overall_score" in result
        assert "evaluations" in result
        assert "warnings" in result
        assert "passed" in result
        assert 0.0 <= result["overall_score"] <= 1.0

        # 四个评估维度都存在
        evals = result["evaluations"]
        assert "SQL Agent" in evals
        assert "Chart Agent" in evals
        assert "Report Agent" in evals
        assert "Debate" in evals

    def test_passing_threshold(self):
        """综合得分 >= 0.5 时 passed=True。"""
        state = {
            "sql_query": "SELECT 1",
            "sql_result": "result_data_here_has_more_than_20_chars_for_testing",
            "sql_error": "",
            "react_iterations": 1,
            "draft_report": "## 分析\n\n根据数据（共统计100条），销售额为 15000 元。\n\n| 项目 | 金额 |\n|------|------|\n| A | 100 |",
            "chart_json": {"data": [{"type": "bar"}]},
            "optimistic_view": "正方：数据显示增长率达到20%，销量最高",
            "pessimistic_view": "反方：但好评率下降3%，需要关注",
            "debate_scores": {"optimistic_score": 80, "pessimistic_score": 65},
        }
        result = evaluate_overall(state)
        assert result["passed"] is True

    def test_failing_state_scores_low(self):
        """所有维度都差时得分低。"""
        state = {
            "sql_query": "",
            "sql_result": "",
            "sql_error": "fatal error",
            "react_iterations": 5,
            "draft_report": "短",
            "chart_json": None,
            "optimistic_view": "",
            "pessimistic_view": "",
            "debate_scores": None,
        }
        result = evaluate_overall(state)
        assert result["overall_score"] < 0.5
        assert result["passed"] is False
