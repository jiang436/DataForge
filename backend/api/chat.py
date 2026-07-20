"""
对话 API — SSE 流式推送 Agent 执行过程

      app/routers/analysis.py

POST /api/chat
  - 从 app.state 获取 Orchestrator → propagate() → SSE 推送给前端

依赖注入说明:
  Orchestrator 通过 FastAPI app.state 管理而非模块级单例。
  应用启动时 lifespan 调用 init_orchestrator() 设置 app.state.orchestrator，
  API 层通过 Request.app.state 获取，测试时可传入 mock。
"""

import json
import logging
import traceback

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.dataflows.sqlite_store import SQLiteStore
from backend.graph.orchestrator import DataAgentGraph
from backend.tools import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def get_orchestrator(app) -> DataAgentGraph:
    """从 FastAPI app.state 获取 orchestor（替代模块级单例）"""
    orch = getattr(app.state, "orchestrator", None)
    if orch is None:
        raise RuntimeError("Orchestrator 未初始化，请检查应用启动配置")
    return orch


def init_orchestrator(app, provider: str, store: SQLiteStore):
    """应用启动时初始化 Orchestrator 并存入 app.state"""
    try:
        from backend.core.config import get_settings
        settings = get_settings()
        orch = DataAgentGraph(
            provider=provider,
            store=store,
            max_debate_rounds=settings.max_debate_rounds,
        )
        app.state.orchestrator = orch
        app.state.llm_provider = provider
        logger.info("Orchestrator 就绪 (app.state), Provider: %s", provider)
        return orch
    except Exception:
        app.state.orchestrator = None
        raise


@router.post("/chat")
async def chat(request: Request):
    """SSE 流式分析 — 支持多轮对话"""
    body = await request.json()
    query = body.get("query", "")
    if not query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")

    tables = body.get("tables", [])
    conversation_id = body.get("conversation_id", "")
    is_follow_up = body.get("follow_up", False)

    logger.info("[API] 分析请求: %s (conversation=%s, follow_up=%s)",
                query[:100], conversation_id or "new", is_follow_up)

    orch = get_orchestrator(request.app)
    store = get_store()
    available_tables = tables or store.get_tables()
    schemas_text = store.get_schemas_text()

    # ─── 多轮对话：注入上轮上下文 ───
    conversation_context = ""
    if is_follow_up and conversation_id:
        from backend.memory.memory_store import get_agent_memory
        memory = get_agent_memory("planner")
        prev = memory.query(f"conversation:{conversation_id}", n=1)
        if prev:
            conversation_context = (
                f"\n## 上轮分析摘要\n{prev[0].get('advice', '')}\n"
                f"## 上轮场景\n{prev[0].get('situation', '')[:800]}\n"
            )

    if conversation_context and query:
        query = f"{query}\n{conversation_context}"

    async def event_generator():
        # asyncio.Queue: 原生 async 队列，无需线程间同步
        import asyncio
        q: asyncio.Queue = asyncio.Queue()

        def _progress_callback(msg):
            # asyncio.Queue.put_nowait: 非阻塞，适合从同步线程推送到 async 消费端
            try:
                q.put_nowait((
                    "step",
                    {"agent": msg.get("agent", "Agent"), "progress": str(msg.get("progress", msg))},
                ))
            except asyncio.QueueFull:
                pass

        def _token_callback(token: str):
            try:
                q.put_nowait(("token", {"token": token, "agent": "llm"}))
            except asyncio.QueueFull:
                pass

        import functools

        def _run(loop):
            """在独立线程中执行 LangGraph 同步图"""
            try:
                from backend.agent.utils.react import set_token_stream_callback
                set_token_stream_callback(_token_callback)

                final_state, performance = orch.propagate(
                    user_query=query,
                    available_tables=available_tables,
                    table_schemas_text=schemas_text,
                    progress_callback=_progress_callback,
                )

                # 提取图表（双路径: Plotly JSON 或 PNG 文件）
                chart = final_state.get("chart_json")
                if not chart:
                    import json as _json
                    for msg in final_state.get("messages", []):
                        c = str(getattr(msg, "content", ""))
                        if len(c) > 200 and '"data"' in c and "plotly" in c.lower():
                            try:
                                chart = _json.loads(c)
                                break
                            except Exception:
                                pass

                chart_files = final_state.get("chart_files", [])

                if chart:
                    asyncio.run_coroutine_threadsafe(
                        q.put(("chart", {"chart_json": chart})), loop
                    )
                elif chart_files:
                    # 高质量路径生成的 PNG 文件
                    asyncio.run_coroutine_threadsafe(
                        q.put(("chart", {"chart_files": chart_files})), loop
                    )

                # 人工审核
                validation_result = final_state.get("validation_result", "")
                if validation_result == "needs_review":
                    asyncio.run_coroutine_threadsafe(q.put(("review", {
                        "draft_report": final_state.get("draft_report", "")[:3000],
                        "validation_reason": final_state.get("validation_reason", ""),
                        "optimistic_view": final_state.get("optimistic_view", "")[:1000],
                        "pessimistic_view": final_state.get("pessimistic_view", "")[:1000],
                        "sql_result": final_state.get("sql_result", "")[:1000],
                    })), loop)

                # 辩论评分
                debate_scores = final_state.get("debate_scores")
                if debate_scores:
                    from backend.agent.debaters.scorer import format_debate_score_for_frontend
                    asyncio.run_coroutine_threadsafe(
                        q.put(("debate_score", format_debate_score_for_frontend(debate_scores))), loop
                    )

                # 评估结果
                evaluation = final_state.get("evaluation")
                if evaluation:
                    asyncio.run_coroutine_threadsafe(q.put(("eval", {
                        "overall_score": evaluation.get("overall_score"),
                        "passed": evaluation.get("passed"),
                        "warnings": evaluation.get("warnings", [])[:5],
                    })), loop)

                # 将报告中的图片路径替换为 base64 内嵌（无需任何文件访问）
                raw_report = final_state.get("final_report", "")
                import re as _re
                converted_report = raw_report
                chart_files = final_state.get("chart_files", [])
                if chart_files:
                    import base64 as _b64
                    for cf in chart_files:
                        try:
                            with open(cf, "rb") as img_file:
                                b64_data = _b64.b64encode(img_file.read()).decode("utf-8")
                            fname = cf.replace("\\", "/").split("/")[-1]
                            # 替换 ![desc](./file.png) 或 ![desc](D:\...\file.png) 为 base64
                            converted_report = _re.sub(
                                rf'!\[([^\]]*)\]\(' + _re.escape(fname) + r'\)',
                                rf'![\1](data:image/png;base64,{b64_data})',
                                converted_report,
                            )
                            converted_report = _re.sub(
                                rf'!\[([^\]]*)\]\(\./' + _re.escape(fname) + r'\)',
                                rf'![\1](data:image/png;base64,{b64_data})',
                                converted_report,
                            )
                            logger.info("[Chat] 图片已嵌入报告: %s (%d bytes)", fname, len(b64_data))
                        except Exception as e:
                            logger.warning("[Chat] 图片嵌入失败: %s - %s", cf, e)

                asyncio.run_coroutine_threadsafe(q.put((
                    "done",
                    {
                        "final_report": converted_report,
                        "performance": performance,
                        "chart_json": chart,
                        "debate_scores": debate_scores,
                        "evaluation": evaluation,
                        "agents": {
                            "planner": {"plan": final_state.get("plan", [])},
                            "sql": {"query": final_state.get("sql_query", "")},
                            "debate": {
                                "optimistic": final_state.get("optimistic_view", ""),
                                "pessimistic": final_state.get("pessimistic_view", ""),
                            },
                            "validator": {
                                "result": final_state.get("validation_result", ""),
                                "reason": final_state.get("validation_reason", ""),
                            },
                        },
                    },
                )), loop)
            except Exception as e:
                logger.error("[API] 异常: %s", traceback.format_exc())
                asyncio.run_coroutine_threadsafe(
                    q.put(("error", {"message": str(e)})), loop
                )
            finally:
                asyncio.run_coroutine_threadsafe(
                    q.put(("__END__", None)), loop
                )

        loop = asyncio.get_running_loop()
        # 共享线程池：避免每请求新建（控制并发线程数）
        from backend.api.thread_pool import get_executor
        future = loop.run_in_executor(get_executor(), functools.partial(_run, loop))

        while True:
            try:
                event_type, data = await q.get()
            except Exception:
                break

            if event_type == "__END__":
                break

            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        await future

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
