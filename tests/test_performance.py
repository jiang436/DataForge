"""性能统计测试"""

from unittest.mock import Mock

from backend.graph.orchestrator import DataAgentGraph


class TestPerformanceTracking:
    """验证 _build_performance 方法正确计算统计数据"""

    def setup_method(self):
        # 创建最小化的 orchestrator（不初始化图，只测性能统计）
        self.graph = DataAgentGraph.__new__(DataAgentGraph)

    def test_empty_timings(self):
        result = self.graph._build_performance({}, 10.0)
        assert result["total_time"] == 10.0
        assert result["node_count"] == 0

    def test_single_node(self):
        result = self.graph._build_performance({"Planner": 1.5}, 3.0)
        assert result["node_count"] == 1
        assert result["total_time"] == 3.0
        assert result["slowest_node"]["name"] == "Planner"
        assert result["slowest_node"]["time"] == 1.5
        assert result["fastest_node"]["name"] == "Planner"

    def test_multiple_nodes(self):
        timings = {
            "Planner": 1.2,
            "SQL Agent": 15.5,
            "Chart Agent": 3.0,
            "Report Agent": 8.0,
            "Validator": 2.0,
        }
        total = sum(timings.values()) + 5.0  # extra overhead
        result = self.graph._build_performance(timings, total)

        assert result["node_count"] == 5
        assert result["slowest_node"]["name"] == "SQL Agent"
        assert result["slowest_node"]["time"] == 15.5
        assert result["fastest_node"]["name"] == "Planner"
        assert result["average_node_time"] > 0

    def test_percentage_sum(self):
        """验证各节点耗时百分比"""
        timings = {"A": 1.0, "B": 1.0, "C": 1.0}
        total = 6.0  # 3s nodes + 3s overhead
        result = self.graph._build_performance(timings, total)

        node_timings = result["node_timings"]
        assert node_timings["A"] == 1.0
        assert node_timings["B"] == 1.0
        assert node_timings["C"] == 1.0

    def test_full_analysis_performance(self):
        """模拟一次完整分析的性能数据"""
        timings = {
            "Planner": 1.47,
            "SQL Agent": 0.12,
            "tools_sql": 13.66,
            "Msg Clear SQL": 3.49,
            "Chart Agent": 1.19,
            "tools_chart": 5.19,
            "Msg Clear Chart": 9.51,
            "Report Agent": 7.60,
            "Optimistic": 2.61,
            "Pessimistic": 4.60,
            "Validator": 2.0,
        }
        total = sum(timings.values()) + 30.0  # LLM API time
        result = self.graph._build_performance(timings, total)

        assert result["node_count"] == 11
        assert result["total_time"] > 50
        # 最慢节点应该是 tools_sql
        assert result["slowest_node"]["name"] == "tools_sql"
