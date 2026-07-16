"""
DataForge AI — FastAPI 主入口
"""

import os
from contextlib import asynccontextmanager

import re as _re
from pathlib import Path as _Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.chat import init_orchestrator
from backend.api.chat import router as chat_router
from backend.api.export import router as export_router
from backend.api.upload import router as upload_router
from backend.core.auth import api_key_middleware
from backend.core.config import get_settings
from backend.core.error_handler import ErrorHandlerMiddleware
from backend.core.rate_limiter import get_rate_limiter
from backend.dataflows.sqlite_store import SQLiteStore
from backend.models.schemas import HealthResponse
from backend.tools import get_store, set_store
from backend.utils.logging_setup import get_logger, setup_logging

settings = get_settings()
setup_logging(level=settings.log_level)
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动: 校验配置 → SQLite → CSV → Graph"""
    logger.info("=" * 60)
    logger.info("DataForge AI 启动中...")
    logger.info("=" * 60)

    # 校验 API Key
    missing_keys = settings.validate_api_keys()
    if missing_keys:
        logger.warning("未配置 API Key 的 Provider: %s", missing_keys)

    os.makedirs(settings.data_dir, exist_ok=True)
    store = SQLiteStore(db_path=settings.db_path)
    set_store(store)

    # 导入 CSV
    if os.path.isdir(settings.data_dir):
        for f in os.listdir(settings.data_dir):
            if f.endswith(".csv"):
                try:
                    store.import_csv(os.path.join(settings.data_dir, f))
                    logger.info("  ✓ %s", f)
                except Exception as e:
                    logger.warning("  ✗ %s: %s", f, e)

    # 初始化 Graph（存入 app.state）
    try:
        init_orchestrator(app, settings.llm_provider, store)
        logger.info("DataAgentGraph 就绪 ✅ (app.state)")
    except Exception as e:
        logger.warning("Graph 初始化失败（需配置 API Key）: %s", e)

    logger.info("已加载表: %s", store.get_tables())
    logger.info("http://localhost:%s/docs", settings.port)
    logger.info("启动完成 ✅")

    yield
    store.close()


app = FastAPI(
    title="DataForge AI",
    description="Multi-Agent 数据分析系统 — 7 Agents + LangGraph + 上下文记忆 + 自适应缓存",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── 中间件 ───
app.add_middleware(ErrorHandlerMiddleware)
app.middleware("http")(api_key_middleware)  # API Key 鉴权（开发模式自动跳过）

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 速率限制 ───
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if settings.rate_limit_enabled:
        limiter = get_rate_limiter()
        client_id = request.client.host if request.client else "unknown"
        if not limiter.acquire(client_id):
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后再试"}},
            )
    return await call_next(request)


# ─── 静态文件: output/ 目录（图表 PNG 等可通过 HTTP 访问） ───
_output_dir = _Path("output")
_output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_output_dir.resolve())), name="output")

# ─── 路由 ───
app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(export_router)

# ─── 报告中的绝对路径 → URL 转换 ───
# 在 chat.py done 事件中调用，将 D:\...\output\session_xxx\charts\file.png
# 转为 /output/session_xxx/charts/file.png
def _convert_chart_paths_to_urls(text: str) -> str:
    """将报告中图表的绝对路径转为可访问的 URL 路径"""
    output_abs = str(_output_dir.resolve()).replace("\\", "/")
    # 匹配 ![desc](D:\...\output\session_xxx\...png) 格式
    text = _re.sub(
        r'!\[([^\]]*)\]\([A-Za-z]:[^)]*?output/(session_[^/]+/charts/[^)]+\.png)\)',
        r'![\1](/output/\2)',
        text,
    )
    # 也处理反斜杠路径
    text = _re.sub(
        r'!\[([^\]]*)\]\([A-Za-z]:[^)]*?output\\(session_[^)]+\.png)\)',
        r'![\1](/output/\2)',
        text,
    )
    return text


@app.get("/api/health", response_model=HealthResponse)
async def health():
    try:
        store = get_store()
        tables = store.get_tables()
        return HealthResponse(status="ok", tables=tables, tables_count=len(tables))
    except Exception as e:
        return HealthResponse(status="error", message=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
