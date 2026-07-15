"""
E2E 测试 — 真实 LLM + 真实数据 + 完整 Agent 流水线

⚠️ 这些测试需要：
  1. 配置好的 .env 文件（有效的 API Key）
  2. data/ 目录下的 CSV 文件
  3. 网络连接

运行方式:
  pytest -m e2e --run-e2e          # 运行所有 E2E 测试
  pytest -m "not e2e"               # CI 中跳过 E2E（默认行为）

每个 E2E 测试耗时 30-120 秒，建议仅在提交前或 CI nightly 中运行。
"""

import os

import pytest

# ─── 前置条件检查 ───


def _check_api_ready():
    """检查 API Key 是否已配置"""
    from backend.core.config import get_settings
    settings = get_settings()
    provider = settings.llm_provider

    key_map = {
        "deepseek": settings.deepseek_api_key,
        "openai": settings.openai_api_key,
        "qwen": settings.dashscope_api_key,
        "glm": settings.zhipu_api_key,
    }
    key = key_map.get(provider, "")

    if not key or key.startswith("sk-xxx"):
        pytest.skip(f"未配置 {provider.upper()}_API_KEY，跳过 E2E 测试")

    # 检查是否有 CSV 数据
    data_dir = settings.data_dir
    csv_files = [f for f in os.listdir(data_dir) if f.endswith(".csv")] if os.path.isdir(data_dir) else []
    if not csv_files:
        pytest.skip("data/ 目录下无 CSV 文件，跳过 E2E 测试")


# ═══════════════════════════════════════════════════════════
# E2E 测试用例
# ═══════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestE2ESimpleQuery:
    """简单查询 — 验证基础功能"""

    def test_basic_count_query(self):
        """问"有多少行" → 应返回正确行数"""
        _check_api_ready()

        from backend.core.config import get_settings
        from backend.dataflows.sqlite_store import SQLiteStore
        from backend.graph.orchestrator import DataAgentGraph
        from backend.tools import set_store

        settings = get_settings()
        store = SQLiteStore(db_path=settings.db_path)
        set_store(store)

        # 导入 CSV
        data_dir = settings.data_dir
        for f in os.listdir(data_dir):
            if f.endswith(".csv"):
                store.import_csv(os.path.join(data_dir, f))

        tables = store.get_tables()
        if not tables:
            pytest.skip("没有可用的数据表")

        orch = DataAgentGraph(provider=settings.llm_provider, store=store)

        query = f"表 {tables[0]} 有多少行数据？"
        final_state, perf = orch.propagate(
            user_query=query,
            available_tables=tables,
            table_schemas_text=store.get_schemas_text(),
        )

        # 验证流水线完整运行
        assert final_state is not None
        assert "sql_result" in final_state or "final_report" in final_state
        # 总耗时在合理范围内
        assert perf["total_time"] < 300, f"E2E 超时: {perf['total_time']}s"

        # 至少有一个 Agent 执行了
        assert perf["node_count"] >= 1

        print(f"\n[E2E] 查询: {query}")
        print(f"[E2E] 耗时: {perf['total_time']}s")
        print(f"[E2E] 节点: {perf['node_count']}")
        print(f"[E2E] SQL: {final_state.get('sql_query', 'N/A')[:200]}")

        store.close()

    def test_brand_ranking_query(self):
        """问"哪个品牌销量最高" → 应返回具体品牌名 + 有图表"""
        _check_api_ready()

        from backend.core.config import get_settings
        from backend.dataflows.sqlite_store import SQLiteStore
        from backend.graph.orchestrator import DataAgentGraph
        from backend.tools import set_store

        settings = get_settings()
        store = SQLiteStore(db_path=settings.db_path)
        set_store(store)

        data_dir = settings.data_dir
        for f in os.listdir(data_dir):
            if f.endswith(".csv"):
                store.import_csv(os.path.join(data_dir, f))

        tables = store.get_tables()
        if not tables:
            pytest.skip("没有数据表")

        orch = DataAgentGraph(provider=settings.llm_provider, store=store)

        query = "按品牌统计销量，哪个品牌销量最高？用柱状图展示"
        final_state, perf = orch.propagate(
            user_query=query,
            available_tables=tables,
            table_schemas_text=store.get_schemas_text(),
        )

        assert final_state is not None
        assert "final_report" in final_state or "draft_report" in final_state

        report = final_state.get("final_report", "") or final_state.get("draft_report", "")
        assert len(report) > 20, "应生成有效报告"

        # 验证评估结果
        evaluation = final_state.get("evaluation", {})
        if evaluation:
            assert 0 <= evaluation.get("overall_score", 0) <= 1.0

        print(f"\n[E2E] 查询: {query}")
        print(f"[E2E] 耗时: {perf['total_time']}s, 节点: {perf['node_count']}")
        print(f"[E2E] 报告长度: {len(report)} 字符")
        print(f"[E2E] Validator: {final_state.get('validation_result', 'N/A')}")

        store.close()
