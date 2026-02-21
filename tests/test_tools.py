"""工具函数测试"""

import json

from backend.tools import execute_sql, generate_chart, set_store


class TestExecuteSQL:
    def test_valid_query(self, store_with_data):
        """测试正常查询"""
        set_store(store_with_data)
        result = execute_sql.invoke({"sql": "SELECT COUNT(*) FROM test_sales"})
        assert "5" in result
        assert "ERROR" not in result

    def test_invalid_query(self, store_with_data):
        """测试无效查询"""
        set_store(store_with_data)
        result = execute_sql.invoke({"sql": "INSERT INTO test_sales VALUES (1)"})
        assert "ERROR" in result

    def test_no_store(self, temp_db):
        """测试未初始化 store"""
        set_store(temp_db)
        result = execute_sql.invoke({"sql": "SELECT 1"})
        assert "1" in result


class TestGenerateChart:
    def test_bar_chart(self):
        """测试柱状图生成"""
        data = [
            {"product": "A", "sales": 100},
            {"product": "B", "sales": 200},
        ]
        result = generate_chart.invoke({
            "chart_type": "bar",
            "title": "Sales by Product",
            "x_column": "product",
            "y_column": "sales",
            "data_json": json.dumps(data),
        })
        assert "ERROR" not in result
        fig = json.loads(result)
        assert "data" in fig
        assert "layout" in fig
        assert len(fig["data"]) == 1

    def test_line_chart_with_group(self):
        """测试多线折线图"""
        data = [
            {"month": "Jan", "product": "A", "sales": 100},
            {"month": "Jan", "product": "B", "sales": 150},
            {"month": "Feb", "product": "A", "sales": 120},
            {"month": "Feb", "product": "B", "sales": 130},
        ]
        result = generate_chart.invoke({
            "chart_type": "line",
            "title": "Trend",
            "x_column": "month",
            "y_column": "sales",
            "data_json": json.dumps(data),
            "group_column": "product",
        })
        assert "ERROR" not in result
        fig = json.loads(result)
        assert len(fig["data"]) == 2  # 2 lines

    def test_empty_data(self):
        """测试空数据"""
        result = generate_chart.invoke({
            "chart_type": "bar",
            "title": "Empty",
            "x_column": "x",
            "y_column": "y",
            "data_json": "[]",
        })
        assert "ERROR" in result
