"""
DataAgentGraph — 主编排器


负责:
  1. 创建 LLM (quick + deep，工厂模式)
  2. 初始化 ConditionalLogic + GraphSetup + Propagator
  3. propagate() — 启动图执行，支持进度回调 + 节点计时
  4. 构建性能数据
  5. v3.1: 会话文件系统隔离（UUID 会话目录，保存所有产物）
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.session import SessionContext
from backend.graph.conditional_logic import ConditionalLogic
from backend.graph.graph_setup import GraphSetup
from backend.graph.propagation import Propagator
from backend.llm_clients import create_deep_llm, create_quick_llm
from backend.memory.reflector import Reflector, get_historical_context
from backend.tools import set_store

logger = logging.getLogger(__name__)


def _is_strict_mode() -> bool:
    """检查是否在严格模式下运行（非网络异常直接抛出）。"""
    try:
        from backend.core.config import get_settings
        return get_settings().strict_mode
    except Exception:
        return False


class DataAgentGraph:
    """
    Multi-Agent 数据分析系统主编排器


    使用方式:
      orchestrator = DataAgentGraph(provider="deepseek", store=sqlite_store)
      # 完整模式（默认）：7 Agent + 辩论 + 评估
      final_state = orchestrator.propagate(user_query="...", ...)

      # 简单模式：跳过辩论和评估，快速出结果
      orchestrator = DataAgentGraph(mode="simple")
      final_state = orchestrator.propagate(user_query="...", ...)
    """

    def __init__(
        self,
        provider: str = "deepseek",
        store=None,
        max_sql_retries: int = 2,
        max_debate_rounds: int = 2,
        mode: str = "full",
    ):
        """
        Args:
            provider: LLM 供应商
            store:    SQLiteStore 实例
            max_sql_retries: SQL 最大重试次数
            max_debate_rounds: 辩论最大轮次
            mode:     "full" (完整模式) | "simple" (简单模式，跳过辩论+评估)
        """
        self.mode = mode

        logger.info("=" * 60)
        logger.info("DataAgentGraph 初始化 (mode=%s)", mode)
        logger.info("=" * 60)

        # ─── 注入 store 给工具层 ───
        if store:
            set_store(store)

        # ─── 创建 LLM ───
        # 创建双 LLM（quick_think + deep_think）
        self.quick_thinking_llm = create_quick_llm(provider)
        self.deep_thinking_llm = create_deep_llm(provider)
        logger.info(
            "LLM 就绪: quick=%s, deep=%s (provider=%s)",
            self.quick_thinking_llm.model_name,
            self.deep_thinking_llm.model_name,
            provider,
        )

        # ─── 条件路由 ───
        self.conditional_logic = ConditionalLogic(
            max_sql_retries=max_sql_retries,
            max_debate_rounds=max_debate_rounds,
        )
        logger.info(
            "ConditionalLogic: sql_retries=%d, debate_rounds=%d", max_sql_retries, max_debate_rounds
        )

        # ─── 传播器 ───
        self.propagator = Propagator(max_recur_limit=50)

        # ─── 图构建 ───
        self.graph_setup = GraphSetup(
            quick_thinking_llm=self.quick_thinking_llm,
            deep_thinking_llm=self.deep_thinking_llm,
            conditional_logic=self.conditional_logic,
            provider=provider,
            mode=mode,
        )
        self.graph = self.graph_setup.setup_graph()

        # 记忆系统
        self.reflector = Reflector(self.quick_thinking_llm)
        self.debate_scorer = None  # 延迟初始化（LLM 已就绪后）
        logger.info("记忆系统就绪")

        # 状态追踪
        self.curr_state = None

    def propagate(
        self,
        user_query: str,
        available_tables: list[str],
        table_schemas_text: str,
        progress_callback: Callable[[str], None] | None = None,
        token_callback: Callable[[str], None] | None = None,
        session_output_dir: str | Path | None = None,
    ) -> tuple[dict, dict]:
        """
        启动 LangGraph 图执行


        Args:
            user_query:         用户问题
            available_tables:   可用表名列表
            table_schemas_text: 表结构文本
            progress_callback:  可选进度回调
            session_output_dir: 可选会话产物输出目录（默认 output/session_<uuid>）

        Returns:
            (final_state, performance_data)
        """
        logger.info("=" * 60)
        logger.info("DataAgentGraph.propagate() 开始执行")
        logger.info("  问题: %s", user_query[:100])
        logger.info("  表: %s", available_tables)
        logger.info("=" * 60)

        # ─── Per-Agent 记忆检索 ───
        # 为每个 Agent 检索其专属历史经验（仿 TradingAgents-CN 模式）
        agent_memory_context = {}
        for agent_name in ["planner", "sql_agent", "chart_agent",
                           "report_agent", "optimistic", "pessimistic", "validator"]:
            ctx = get_historical_context(agent_name, user_query, n=2)
            if ctx:
                agent_memory_context[agent_name] = ctx
        # Planner 获取主上下文（向后兼容）
        historical_context = agent_memory_context.get("planner", "")

        if agent_memory_context:
            logger.info(
                "Per-Agent 记忆: %d/%d Agent 有历史经验",
                len(agent_memory_context), 7,
            )

        # ─── 会话目录（参考 data_analysis_agent: 报告和图表同目录） ───
        import uuid as _uuid
        session_id = _uuid.uuid4().hex[:12]
        session_dir = Path(session_output_dir or "output") / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[Session] 会话目录: %s", session_dir)

        # ─── 创建初始状态 ───
        init_state = self.propagator.create_initial_state(
            user_query=user_query,
            available_tables=available_tables,
            table_schemas_text=table_schemas_text,
            historical_context=historical_context,
            agent_memory_context=agent_memory_context,
        )
        # 注入会话目录，Chart Agent 和 Report 共用
        init_state["_session_id"] = session_id
        init_state["_session_dir"] = str(session_dir)

        # ─── 计时器 + 流模式 ───
        node_timings = {}
        total_start = time.time()
        current_node_name = None
        current_node_start = None
        final_state = None

        args = self.propagator.get_graph_args(use_progress_callback=bool(progress_callback))

        logger.info("流模式: %s", args["stream_mode"])

        # ─── 执行图 ───
        # 流式执行图
        try:
            for chunk in self.graph.stream(init_state, **args):
                # ─── 提取节点名 + 计时 ───
                for node_name in chunk.keys():
                    if node_name.startswith("__"):
                        continue

                    # 记录上一节点耗时
                    if current_node_name and current_node_start:
                        elapsed = time.time() - current_node_start
                        node_timings[current_node_name] = elapsed
                        logger.info("⏱️ [%s] 耗时: %.2f秒", current_node_name, elapsed)

                    current_node_name = node_name
                    current_node_start = time.time()
                    break

                # ─── 进度回调 ───
                if progress_callback and args.get("stream_mode") == "updates":
                    self._send_progress(chunk, progress_callback)

                # ─── 累积状态 ───
                if final_state is None:
                    final_state = init_state.copy()
                for node_name, node_update in chunk.items():
                    if not node_name.startswith("__"):
                        final_state.update(node_update)

        except Exception as e:
            logger.error("图执行异常: %s", e, exc_info=True)
            raise

        # ─── 最后一个节点计时 ───
        if current_node_name and current_node_start:
            elapsed = time.time() - current_node_start
            node_timings[current_node_name] = elapsed

        total_elapsed = time.time() - total_start

        # ─── 性能数据 ───
        performance = self._build_performance(node_timings, total_elapsed)
        if final_state:
            final_state["performance_metrics"] = performance

        # ─── 辩论评分（完整模式） ───
        if self.mode != "simple" and final_state and final_state.get("optimistic_view"):
            try:
                from backend.agent.debaters.scorer import DebateScorer
                if self.debate_scorer is None:
                    self.debate_scorer = DebateScorer(self.quick_thinking_llm)
                scores = self.debate_scorer.score(final_state)
                final_state["debate_scores"] = dict(scores)
                logger.info(
                    "辩论评分完成: 正方=%d 反方=%d",
                    scores.get("optimistic_score", 0),
                    scores.get("pessimistic_score", 0),
                )
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning("辩论评分失败（网络问题）: %s", e)
            except (ValueError, TypeError, KeyError) as e:
                logger.error("辩论评分失败（配置或数据错误）: %s", e, exc_info=True)
                if _is_strict_mode():
                    raise
            except Exception as e:
                logger.warning("辩论评分失败（非致命）: %s — 可能原因: LLM未配置或评分prompt超时", e)

        # ─── 评估（完整模式） ───
        if self.mode != "simple" and final_state:
            try:
                from backend.eval import evaluate_overall
                evaluation = evaluate_overall(final_state)
                final_state["evaluation"] = evaluation
                logger.info(
                    "评估完成: 总分=%.2f, 警告=%d",
                    evaluation["overall_score"],
                    len(evaluation["warnings"]),
                )
            except (ValueError, TypeError, KeyError) as e:
                logger.error("评估失败（数据错误）: %s", e, exc_info=True)
                if _is_strict_mode():
                    raise
            except Exception as e:
                logger.warning("评估失败（非致命）: %s", e)

        # ─── 反思学习 ───
        if final_state and final_state.get("validation_result") == "approved":
            try:
                self.reflector.reflect_and_remember(final_state)
                logger.info("反思学习完成，经验已存入记忆")
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning("反思学习失败（网络问题）: %s", e)
            except (ValueError, TypeError) as e:
                logger.error("反思学习失败（配置错误）: %s", e, exc_info=True)
                if _is_strict_mode():
                    raise
            except Exception as e:
                logger.warning("反思学习失败（非致命）: %s", e)

        # DEBUG: check if chart_json survived to final_state
        if final_state:
            import datetime as _dt3
            with open("debug_orch.log", "a", encoding="utf-8") as df:
                has_chart = bool(final_state.get("chart_json"))
                df.write(f"{_dt3.datetime.now()} [Orch] chart_json in final_state: {has_chart}\n")
                if not has_chart:
                    df.write(f"  final_state keys: {list(final_state.keys())[:20]}\n")

        # ═══ 打印性能报告 ═══
        logger.info("=" * 60)
        logger.info("⏱️ 分析完成 — 总耗时: %.2f秒", total_elapsed)
        for node_name, elapsed in node_timings.items():
            pct = (elapsed / total_elapsed * 100) if total_elapsed > 0 else 0
            logger.info("  %-20s %7.2f秒 (%5.1f%%)", node_name, elapsed, pct)
        logger.info("=" * 60)

        # ═══ 会话产物持久化 — 参考 data_analysis_agent: 报告和图表同目录 ═══
        if final_state:
            try:
                session_dir = Path(final_state.get("_session_dir", ""))
                if session_dir.exists():
                    # 保存最终报告到会话目录（与图表 PNG 同级）
                    report = final_state.get("final_report", "")
                    if report:
                        (session_dir / "report.md").write_text(report, encoding="utf-8")
                        logger.info("[Session] 报告已保存: %s", session_dir / "report.md")

                    # 也保存分层报告树
                    from backend.utils.report_exporter import export_report_tree
                    export_report_tree(final_state, output_dir=str(session_dir))
                    logger.info("[Session] 会话产物完成: %s", session_dir)
            except Exception as e:
                logger.warning("[Session] 会话保存失败（非致命）: %s", e)

        self.curr_state = final_state
        return final_state, performance

    def _send_progress(self, chunk: dict, callback: Callable[[dict], None]):
        """Send progress with agent name"""
        try:
            for key in chunk.keys():
                if not key.startswith("__"):
                    label = self.propagator.get_progress_label(key)
                    if label:
                        logger.debug("[进度] %s -> %s", key, label)
                        callback({"agent": key, "progress": label})
                    break
        except Exception as e:
            logger.warning("进度回调失败: %s", e)

    def _build_performance(
        self, node_timings: dict[str, float], total_elapsed: float
    ) -> dict[str, Any]:
        """
        构建性能数据

        """
        if not node_timings:
            return {"total_time": total_elapsed, "node_count": 0}

        slowest = max(node_timings.items(), key=lambda x: x[1])
        fastest = min(node_timings.items(), key=lambda x: x[1])
        avg_time = sum(node_timings.values()) / len(node_timings)

        return {
            "total_time": round(total_elapsed, 2),
            "node_count": len(node_timings),
            "average_node_time": round(avg_time, 2),
            "slowest_node": {"name": slowest[0], "time": round(slowest[1], 2)},
            "fastest_node": {"name": fastest[0], "time": round(fastest[1], 2)},
            "node_timings": {k: round(v, 2) for k, v in node_timings.items()},
        }
