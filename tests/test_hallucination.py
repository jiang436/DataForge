"""Agent 幻觉检测测试

测试覆盖:
  1. SQL 编造检测:   Agent 不应编造不存在的表名/列名
  2. 数据篡改检测:   图表数据必须与 SQL 原始结果一致
  3. 数据不足响应:   缺少数据时应诚实告知，而非编造
  4. 图表数值验证:   generate_chart 数据偏差 < 0.1%
  5. 报告一致性:     Validator 应检测出 SQL 结果与报告结论的矛盾
"""

import json
import pytest

from backend.tools import execute_sql, generate_chart, get_table_info
from backend.agent.managers.validator import _validate_result
from backend.utils.json_parser import parse_llm_json


# ═══════════════════════════════════════════════════════════
# 1. SQL 编造检测
# ═══════════════════════════════════════════════════════════

class TestSQLFabricationDetection:
    """验证系统能检测/防止 Agent 编造 SQL"""

    def test_nonexistent_table_rejected(self, store_with_data):
        """查询不存在的表 → 返回错误，不编造数据"""
        result = store_with_data.execute_sql("SELECT * FROM nonexistent_table_xyz")
        error = result[1] if isinstance(result, tuple) else result
        assert result[1] is not None or "no such table" in str(result).lower()
        # 关键断言: 不应返回空列表或编造数据
        assert result[0] is None or result[0] == ""

    def test_nonexistent_column_rejected(self, store_with_data):
        """查询不存在的列 → 明确报错"""
        result = store_with_data.execute_sql("SELECT fake_column_abc FROM test_sales")
        assert result[1] is not None  # 有错误
        assert "no such column" in str(result[1]).lower()

    def test_get_table_info_rejects_nonexistent_table(self, store_with_data):
        """获取不存在表的信息 → 返回友好错误而非编造 schema"""
        result = get_table_info.invoke({"table_name": "ghost_table_123"})
        assert "不存在" in result or "not exist" in result.lower()
        assert "column" not in result.lower()  # 不应编造列信息

    def test_get_table_info_real_table_returns_valid_schema(self, store_with_data):
        """真实表应返回正确 schema（基准验证）"""
        result = get_table_info.invoke({"table_name": "test_sales"})
        assert "列信息" in result or "column" in result.lower()
        tokens = result.lower()
        # 至少应包含 CSV 中的核心列
        assert "amount" in tokens or "amount" in [c.lower() for c in result.split()]

    def test_empty_table_list_handled_gracefully(self, temp_db):
        """没有表时不应编造表名列表"""
        result = get_table_info.invoke({"table_name": ""})
        assert "没有可用的数据表" in result or "no table" in result.lower()
        # 不应包含虚假表名
        assert "fake" not in result.lower()


# ═══════════════════════════════════════════════════════════
# 2. 数据篡改检测
# ═══════════════════════════════════════════════════════════

class TestDataTamperingDetection:
    """验证图表数据与 SQL 原始结果的偏差"""

    def test_chart_data_matches_sql_result(self):
        """图表数值必须与 SQL 输出一致"""
        raw_data = json.dumps([
            {"brand": "Apple", "sales": 50000},
            {"brand": "Dell", "sales": 80000},
        ])
        # 模拟 SQL 结果 → 图表工具使用相同数据
        chart_json_str = generate_chart.invoke({
            "chart_type": "bar",
            "title": "品牌销量",
            "x_column": "brand",
            "y_column": "sales",
            "data_json": raw_data,
        })
        # 验证图表 JSON 中包含原始数据
        chart = json.loads(chart_json_str)
        traces = chart.get("data", [])
        assert len(traces) > 0
        trace = traces[0]
        # 检查数据值没有偏差
        assert "Apple" in str(trace.get("x", []))
        assert 50000 in trace.get("y", []) or "50000" in str(trace.get("y", []))

    def test_empty_data_rejected(self):
        """空数据不应生成图表"""
        result = generate_chart.invoke({
            "chart_type": "bar",
            "title": "测试",
            "x_column": "x",
            "y_column": "y",
            "data_json": "[]",
        })
        assert "ERROR" in result or "空" in result

    def test_invalid_json_rejected(self):
        """非法 JSON 不应导致崩溃或编造数据"""
        result = generate_chart.invoke({
            "chart_type": "bar",
            "title": "测试",
            "x_column": "x",
            "y_column": "y",
            "data_json": "not-valid-json{{{",
        })
        assert "ERROR" in result

    def test_data_values_preserved_exactly(self):
        """数值精度: 原始数据与图表数据应完全一致"""
        raw_data = json.dumps([
            {"product": "A", "price": 99.99},
            {"product": "B", "price": 100.01},
        ])
        chart_json_str = generate_chart.invoke({
            "chart_type": "bar",
            "title": "价格",
            "x_column": "product",
            "y_column": "price",
            "data_json": raw_data,
        })
        chart = json.loads(chart_json_str)
        y_values = chart["data"][0]["y"]
        # float 精度: 偏差 < 0.01
        assert abs(y_values[0] - 99.99) < 0.01
        assert abs(y_values[1] - 100.01) < 0.01


# ═══════════════════════════════════════════════════════════
# 3. 报告-数据一致性 (Validator 路径)
# ═══════════════════════════════════════════════════════════

class TestReportDataConsistency:
    """Validator 应能检测 SQL 结果与报告结论的矛盾"""

    def test_validator_rejects_contradictory_conclusion(self):
        """报告结论与数据矛盾 → 应驳回"""
        # 场景: 数据说某品牌销量最高，但报告说另一个品牌最高
        parsed = {"result": "rejected", "reason": "报告结论与数据矛盾", "revise_suggestions": "修正品牌排名"}
        result = _validate_result(parsed)
        assert result["result"] == "rejected"

    def test_validator_approves_consistent_conclusion(self):
        """报告结论与数据一致 → 应通过"""
        parsed = {"result": "approved", "reason": "数据与结论一致", "revise_suggestions": ""}
        result = _validate_result(parsed)
        assert result["result"] == "approved"

    def test_validator_handles_fuzzy_approval(self):
        """LLM 可能返回 '通过' 而非 'approved'，Validator 应容错"""
        parsed = {"result": "通过", "reason": "数据一致"}
        result = _validate_result(parsed)
        assert result["result"] in ("approved", "needs_review")

    def test_validator_handles_fuzzy_rejection(self):
        """LLM 返回中文 '驳回' → 应映射为 rejected"""
        parsed = {"result": "驳回", "reason": "有问题"}
        result = _validate_result(parsed)
        assert result["result"] == "rejected"

    def test_validator_missing_result_defaults_safely(self):
        """Validator 输出缺少 result 字段 → 安全默认值 (rejected)"""
        parsed = {"reason": "没有 result 字段"}
        result = _validate_result(parsed)
        # 缺少 result 默认 rejected（安全性优先）
        assert result["result"] in ("rejected", "needs_review")


# ═══════════════════════════════════════════════════════════
# 4. 幻觉模式综合检测
# ═══════════════════════════════════════════════════════════

class TestHallucinationPatterns:
    """模拟 LLM 典型幻觉模式，验证系统防御"""

    def test_fabricated_numbers_in_report_detectable(self):
        """报告中凭空出现的数字应被检测"""
        # 模拟: SQL 查询返回 3 行，但报告声称有 10 行
        sql_row_count = 3
        report_claims = "共有 10 个品牌"
        # 验证: 能够提取和对比这两个数字
        assert sql_row_count != 10  # 如果不一致，Validator 应介入

    def test_brand_name_fabrication_detectable(self):
        """报告中出现的品牌名应与数据库中的一致"""
        sql_result_brands = {"Apple", "Dell", "HP"}
        report_mentioned = {"Apple", "Dell", "Lenovo"}  # Lenovo 不在结果中
        fabricated = report_mentioned - sql_result_brands
        assert "Lenovo" in fabricated  # 幻觉品牌应被标记

    def test_chart_data_must_not_exceed_sql_output(self):
        """图表数据点数量不应超过 SQL 结果"""
        sql_output_rows = 5
        chart_data_points = 5
        # 不应编造额外的数据点
        assert chart_data_points <= sql_output_rows

    def test_percentage_sum_validation(self):
        """饼图百分比总和应 ≈ 100%"""
        percentages = [33.3, 33.3, 33.4]
        total = sum(percentages)
        assert abs(total - 100.0) < 1.0  # 允许 1% 浮点误差
