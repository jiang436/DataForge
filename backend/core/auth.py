"""
API Key 鉴权中间件

通过 X-API-Key header 或 ?api_key= query param 验证请求。
配置: .env 中的 DATA_FORGE_API_KEY（不设置则跳过验证，开发模式）
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.core.config import get_settings

logger = logging.getLogger("auth")

# 不需要鉴权的路径
_PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


async def api_key_middleware(request: Request, call_next):
    """API Key 验证中间件"""
    # 公开路径跳过
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/docs"):
        return await call_next(request)

    settings = get_settings()
    expected_key = settings.api_key

    # 未配置 API Key → 允许所有请求（开发模式）
    if not expected_key:
        return await call_next(request)

    # 从 Header 或 Query 获取
    actual_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

    if not actual_key:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "UNAUTHORIZED", "message": "缺少 API Key。请在 Header 中传递 X-API-Key 或 Query 中传递 ?api_key="}},
        )

    # 常量时间比较，防止时序攻击
    import hmac
    if not hmac.compare_digest(actual_key, expected_key):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "FORBIDDEN", "message": "API Key 无效"}},
        )

    return await call_next(request)
