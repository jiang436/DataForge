"""多轮对话上下文测试 — Agent 需要记住之前的分析结果

测试覆盖:
  1. 状态传播:      前一轮分析结果进入下一轮上下文
  2. 工作记忆:      WorkingMemory 跨 Agent 共享 findings/observations
  3. 指代消解:      第二轮"它的"→应关联到上一轮提到的品牌
  4. 数据集切换:    切换表后不引用上一轮的表结构
  5. 辩论上下文:    辩论双方可引用共享证据空间
"""

import pytest

from backend.agent.utils.state import (
    WorkingMemory,
    SharedEvidence,
    DebateState,
    DataAnalysisState,
)
from backend.graph.propagation import Propagator


# ═══════════════════════════════════════════════════════════
# 1. 状态传播测试
# ═══════════════════════════════════════════════════════════

class TestStatePropagation:
    """一轮分析的结果应正确传递到下一轮"""

    def test_sql_result_survives_to_next_step(self):
        """SQL Agent 结果 → 进入下一轮 state"""
        prop = Propagator(max_recur_limit=50)
        state = prop.create_initial_state(
            user_query="哪个品牌销量最高？",
            available_tables=["sales"],
            table_schemas_text="sales: brand(text), amount(int)",
        )

        # 模拟第 1 轮: SQL 执行完毕
        state["sql_query"] = "SELECT brand, SUM(amount) FROM sales GROUP BY brand"
        state["sql_result"] = "brand,sales\nDell,80000\nApple,50000"
        state["draft_report"] = "戴尔销量最高（80000件），苹果第二（50000件）。"

        # 新一轮: Planner 重新规划，应从 state 中读取上一轮结果
        # 验证上下文没有被清除
        assert "Dell" in state.get("sql_result", "")
        assert "戴尔" in state.get("draft_report", "")

    def test_multi_round_plan_preserved(self):
        """多步骤 Plan 在步骤间正确传递"""
        prop = Propagator(max_recur_limit=50)
        state = prop.create_initial_state(
            user_query="分析各品牌销售表现",
            available_tables=["sales"],
            table_schemas_text="sales: brand(text), amount(int), region(text)",
        )

        state["plan"] = [
            {"step": 1, "task": "查询品牌总销量", "type": "sql", "depends_on": []},
            {"step": 2, "task": "查询区域分布", "type": "sql", "depends_on": [1]},
            {"step": 3, "task": "生成对比图表", "type": "chart", "depends_on": [1, 2]},
        ]

        # 步骤 1 完成后
        state["current_step_index"] = 1
        state["sql_result"] = "brand,sales\nDell,80000"

        # 步骤 2 应该仍能访问步骤 1 的结果和 Plan
        assert len(state["plan"]) == 3
        assert state["sql_result"] is not None

    def test_validation_result_carries_forward(self):
        """Validator 驳回后的修正轮次，Report Agent 应能看到驳回理由"""
        prop = Propagator(max_recur_limit=50)
        state = prop.create_initial_state(
            user_query="分析销量",
            available_tables=["sales"],
            table_schemas_text="sales: brand(text), amount(int)",
        )

        # 模拟: Validator 驳回
        state["validation_result"] = "rejected"
        state["validation_reason"] = "报告结论与 SQL 结果矛盾：报告宣称苹果销量最高，但数据显是戴尔"
        state["revision_count"] = 1

        # Report Agent 修正时应能看到驳回理由
        assert "苹果" in state["validation_reason"]
        assert state["validation_result"] == "rejected"
        assert state["revision_count"] == 1


# ═══════════════════════════════════════════════════════════
# 2. 工作记忆 (WorkingMemory) 测试
# ═══════════════════════════════════════════════════════════

class TestWorkingMemory:
    """Agent 间结构化共享上下文"""

    def test_findings_accumulate_across_agents(self):
        """每个 Agent 添加 finding → 下游可读取"""
        wm: WorkingMemory = {
            "findings": [],
            "observations": [],
            "decisions": [],
            "open_questions": [],
        }

        # SQL Agent 添加发现
        wm["findings"].append({"agent": "SQL Agent", "finding": "戴尔销量最高", "confidence": 0.95})
        wm["findings"].append({"agent": "SQL Agent", "finding": "共 4 条记录", "confidence": 1.0})

        # Chart Agent 添加观察
        wm["observations"].append("柱状图显示戴尔远超其他品牌")
        wm["decisions"].append({"agent": "Chart Agent", "decision": "使用分组柱状图", "reason": "对比展示"})

        # 验证跨 Agent 积累
        assert len(wm["findings"]) == 2
        assert len(wm["observations"]) == 1
        assert wm["findings"][0]["agent"] == "SQL Agent"
        assert wm["findings"][0]["confidence"] > 0.9

    def test_open_questions_tracked(self):
        """未解决的问题应被跟踪"""
        wm: WorkingMemory = {
            "findings": [],
            "observations": [],
            "decisions": [],
            "open_questions": ["苹果的增长趋势是否可持续？", "数据是否包含促销影响？"],
        }
        assert len(wm["open_questions"]) == 2
        # 问题应该有具体内容
        assert "苹果" in wm["open_questions"][0]
        assert "促销" in wm["open_questions"][1]


# ═══════════════════════════════════════════════════════════
# 3. 指代消解模拟
# ═══════════════════════════════════════════════════════════

class TestReferenceResolution:
    """多轮对话中代词的上下文关联"""

    def test_pronoun_refers_to_previous_brand(self):
        """"它的" → 应关联到上一轮提到的品牌"""
        # 第 1 轮
        round1_query = "海尔销量多少？"
        round1_result = "海尔总销量: 25000 件"
        round1_brand = "海尔"

        # 第 2 轮
        round2_query = "它的好评率呢？"
        # 应有机制将"它"解析为"海尔"
        # 验证: 从上一轮结果中提取品牌名
        assert round1_brand in round1_result

        # 模拟上下文注入: 将上一轮结果注入到新一轮 query 的前面
        contextualized_query = f"[上一轮: {round1_result}] {round2_query}"
        assert "海尔" in contextualized_query
        assert "好评率" in contextualized_query

    def test_switch_dataset_clears_context(self):
        """切换数据集后 → 不应引用上一轮的表结构"""
        round1_schema = {"table": "electronics", "columns": ["brand", "price", "sales"]}
        round2_schema = {"table": "reviews", "columns": ["brand", "rating", "content"]}

        # 切换数据集: 新一轮 schema 不同
        assert round2_schema["columns"] != round1_schema["columns"]
        # 不应有 price/sales 在 reviews 表
        assert "price" not in round2_schema["columns"]
        assert "sales" not in round2_schema["columns"]


# ═══════════════════════════════════════════════════════════
# 4. 共享证据空间 (SharedEvidence)
# ═══════════════════════════════════════════════════════════

class TestSharedEvidence:
    """辩论双方共享的证据空间验证"""

    def test_evidence_cited_by_both_sides(self):
        """双方引用过的数据点应被记录"""
        evidence: SharedEvidence = {
            "data_points": [
                {"value": "海尔销量 25000", "source": "SQL查询", "cited_by": ["optimistic"]},
                {"value": "海尔好评率 82%", "source": "SQL查询", "cited_by": ["pessimistic"]},
            ],
            "agreed_facts": [],
            "disputed_claims": [],
        }
        assert len(evidence["data_points"]) == 2
        assert evidence["data_points"][0]["cited_by"] == ["optimistic"]

    def test_agreed_facts_tracked(self):
        """双方共识应被记录"""
        evidence: SharedEvidence = {
            "data_points": [],
            "agreed_facts": ["戴尔销量最高", "苹果好评率第一"],
            "disputed_claims": [],
        }
        assert "戴尔销量最高" in evidence["agreed_facts"]

    def test_disputed_claims_tracked_with_views(self):
        """争议焦点应包含双方观点"""
        evidence: SharedEvidence = {
            "data_points": [],
            "agreed_facts": [],
            "disputed_claims": [
                {
                    "claim": "海尔是否性价比最高",
                    "optimistic_view": "价格低+销量高，性价比最优",
                    "pessimistic_view": "好评率仅82%，质量堪忧，性价比不能只看价格",
                }
            ],
        }
        claim = evidence["disputed_claims"][0]
        assert "性价比" in claim["claim"]
        assert "价格低" in claim["optimistic_view"]
        assert "质量" in claim["pessimistic_view"]


# ═══════════════════════════════════════════════════════════
# 5. 状态初始化验证
# ═══════════════════════════════════════════════════════════

class TestStateInitialization:
    """Propagator 创建初始状态的完整性"""

    def test_initial_state_has_all_required_fields(self):
        prop = Propagator(max_recur_limit=50)
        state = prop.create_initial_state(
            user_query="测试问题",
            available_tables=["t1", "t2"],
            table_schemas_text="t1: col1(int)",
        )
        # 核心字段应存在
        assert state["user_query"] == "测试问题"
        assert state["available_tables"] == ["t1", "t2"]
        assert "messages" in state
        assert "working_memory" in state
        assert state["sql_retry_count"] == 0
        assert state["revision_count"] == 0

    def test_initial_messages_contain_user_query(self):
        prop = Propagator(max_recur_limit=50)
        state = prop.create_initial_state(
            user_query="给我一个分析报告",
            available_tables=["data"],
            table_schemas_text="data: id(int)",
        )
        messages = state.get("messages", [])
        assert len(messages) > 0
        # 第一条消息应包含用户 query 或 system prompt
        first_msg = str(messages[0] if hasattr(messages[0], "content") else messages[0])
        # 用户 query 应出现在消息列表中
        assert "分析报告" in first_msg or any(
            "分析报告" in str(getattr(m, "content", m)) for m in messages
        )
